"""The tool registry, its gates, and the taint label (SPEC.md §19, §18.1, §0.4).

Split out of `tools.py` for a layering reason rather than a stylistic one.
`context.py` has to render two things — what a Cell may *request* (§0.4) and
what a previous tool call *returned* (§19.4's fenced section) — but `tools.py`
sits at the very top of the dependency order, importing `approval`, which
imports `deliberation`, which imports `context`. A direct import would close
that loop.

The split follows the kernel's existing rule: when a lower layer needs
behaviour from a higher one, invert rather than back-edge. Everything here
depends only on `audit`, `ids` and `models`, so both `context` (below) and
`tools` (above) can import it. What stayed in `tools.py` is exactly the part
that *executes* — the grant consumer — which is also the part §19.4 requires
`context` be unable to reach. **The layering and the prompt-injection boundary
turn out to want the same cut**, which is a good sign that the cut is real:
`context` can read tool results and list tool names, and has no path to
running one.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from . import audit
from .models import CellStatus

#: §25.1's rung a read-only observation issues.
LADDER_RUNG_READ_ONLY_OBSERVATION = 4

#: §18.1's label for anything that came from outside the colony. Every tool
#: result gets this and nothing in the kernel can change it — §18.3's
#: clean-room path is the only route to another label and is not built.
TAINT_UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"

#: Response ceiling. §19.3 requires runtime/disk limits; without a cap here one
#: fetch could blow the §15 context budget of every later wake, which is a
#: denial-of-service against the Cell's own thinking.
MAX_RESULT_BYTES = 64_000

#: What one tool call costs in metered RESOURCE. A fetch moves no USD_REAL, so
#: — exactly as with `OllamaProvider` — metering is the *only* bound on how
#: much of it a Cell can do.
RESOURCE_COST_PER_CALL = 5

#: How long a tool call's RESOURCE reservation stands before the sweeper may
#: consider it stranded. Generous relative to a fetch, because a reservation
#: reaped mid-call is worse than one held slightly too long.
_RESERVATION_TTL = timedelta(minutes=15)

#: Where metered RESOURCE settles: the Cell consumed infrastructure and paid
#: the colony for it (`accounts.SPEND_DESTINATIONS`).
_INFRASTRUCTURE_RESERVE = "infrastructure_reserve"

#: Charter C8 / §18.2. Mirrors `deliberation._CAN_DELIBERATE` — a dormant Cell
#: is the ordinary case for one waiting on a fetch, so requiring ALIVE would
#: make the tool path unusable for exactly the Cells §17.2 is designed around.
_CAN_RECEIVE_TOOL_RESULT = frozenset({CellStatus.ALIVE, CellStatus.DORMANT})


class ToolError(Exception):
    pass


class EgressRefused(ToolError):
    """§19.3: the domain is not on the allowlist. Charter C12."""


class AutonomyRefused(ToolError):
    """§27.1: the autonomy flag gating this tool is off."""


# --- the registry -------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One capability, and the gate that governs it.

    `autonomy_flag` names a §27.1 `autonomy:` key rather than carrying a
    boolean, because §0.4 grants autonomy "tool by tool" and the operator
    turns those keys on one at a time. A tool with no flag would be a
    capability nobody ever decided to allow.
    """

    tool_id: str
    description: str
    autonomy_flag: str
    #: §25.1. True = rung 4 observation. False = rungs 8-9, and a named test
    #: refuses it — see the module docstring.
    read_only: bool
    parameters: dict[str, str]
    validate: Callable[[dict[str, Any]], None]
    #: Which argument carries a URL, if any. Naming it here rather than
    #: special-casing `http_get` in the executor means a future tool that
    #: reaches the network cannot forget the Charter C12 allowlist check — it
    #: either declares the argument or it has no egress at all.
    egress_argument: str | None = None


def _validate_http_get(arguments: dict[str, Any]) -> None:
    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ToolError("http_get requires a 'url' string")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ToolError(f"http_get supports http/https only, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise ToolError(f"http_get could not read a hostname from {url!r}")
    unknown = set(arguments) - {"url"}
    if unknown:
        raise ToolError(f"unknown http_get arguments: {', '.join(sorted(unknown))}")


REGISTRY: dict[str, ToolSpec] = {
    "http_get": ToolSpec(
        tool_id="http_get",
        description="Fetch one URL and return its text. Read-only; follows no links.",
        autonomy_flag="public_web_read",
        read_only=True,
        parameters={"url": "the absolute http(s) URL to fetch"},
        validate=_validate_http_get,
        egress_argument="url",
    ),
}


def get_spec(tool_id: str) -> ToolSpec:
    spec = REGISTRY.get(tool_id)
    if spec is None:
        raise ToolError(
            f"unknown tool {tool_id!r}. Registered: "
            f"{', '.join(sorted(REGISTRY)) or '(none)'}"
        )
    return spec


def validate_request(tool_id: str, arguments: dict[str, Any]) -> ToolSpec:
    """Check a tool request without running anything.

    Used at proposal time so a Cell asking for a tool that does not exist is
    told at parse time, and at execution time again — the second check is not
    redundant, because the registry can change between a proposal and its
    approval.
    """
    spec = get_spec(tool_id)
    spec.validate(arguments)
    return spec


# --- the execution seam -------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    text: str
    http_status: int
    source: str
    #: §20.1. Supplied by the fetcher rather than defaulted, because §20.2 is
    #: explicit that public visibility does not imply commercial reusability
    #: and a default here would be a fabricated licence claim.
    licence: str
    permitted_uses: str
    commercial_use: str
    contains_personal_data: bool


class Fetcher(Protocol):
    """The one place this module touches a network.

    An injected seam for the same reason `providers.Provider` is one: the
    kernel and its whole test suite must run with no network, and a default
    that quietly worked would mean tests silently making real requests.
    """

    def fetch(self, url: str, *, max_bytes: int) -> FetchResult: ...


class RefusingFetcher:
    """The default. Refuses everything.

    A no-network default is §19.3's "network disabled by default" expressed as
    code: a caller that has not deliberately supplied a fetcher does not get
    one, and the failure is loud rather than a silent request.
    """

    def fetch(self, url: str, *, max_bytes: int) -> FetchResult:
        raise ToolError(
            "no fetcher configured — §19.3 ships the network disabled. Supply a "
            "fetcher explicitly to make a real request."
        )


# --- §19.3 egress allowlist (Charter C12) -------------------------------------


def allow_domain(
    conn: sqlite3.Connection, *, domain: str, added_by: str, reason: str
) -> None:
    """Add one domain to the egress allowlist. Always audited.

    Audited in both directions like `scheduler.set_real_spending`, and for the
    same reason: this is the boundary of what the colony can reach, so a change
    to it is a governance event rather than configuration.
    """
    domain = _normalise_domain(domain)
    reason = (reason or "").strip()
    if not reason:
        raise ToolError("adding a domain to the egress allowlist must state a reason")

    now = datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT OR REPLACE INTO egress_allowlist (domain, added_at_utc, added_by, reason) "
            "VALUES (?, ?, ?, ?)",
            (domain, now.isoformat(), added_by, reason),
        )
        audit.record(
            conn,
            event_type="egress_domain_allowed",
            cell_id=None,
            description=f"egress allowlist += {domain}: {reason}",
            metadata={"domain": domain, "added_by": added_by},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def deny_domain(conn: sqlite3.Connection, *, domain: str, removed_by: str) -> None:
    domain = _normalise_domain(domain)
    now = datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM egress_allowlist WHERE domain = ?", (domain,))
        audit.record(
            conn,
            event_type="egress_domain_denied",
            cell_id=None,
            description=f"egress allowlist -= {domain}",
            metadata={"domain": domain, "removed_by": removed_by, "at": now.isoformat()},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def allowed_domains(conn: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        r["domain"] for r in conn.execute("SELECT domain FROM egress_allowlist ORDER BY domain")
    )


def _normalise_domain(domain: str) -> str:
    domain = (domain or "").strip().lower().rstrip(".")
    if not domain or "/" in domain or ":" in domain:
        raise ToolError(f"not a bare domain: {domain!r}")
    return domain


def _check_egress_locked(conn: sqlite3.Connection, url: str) -> str:
    """Charter C12: refuse any host not explicitly allowed.

    **Matching is exact or a dotted suffix, never a substring.** A substring
    test would let `evil-example.com` past an allowlist containing
    `example.com`, and a bare `endswith` would let `notexample.com` past it
    too — which is why the suffix compared is `"." + domain`.
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        raise EgressRefused(f"no hostname in {url!r}")
    for domain in allowed_domains(conn):
        if host == domain or host.endswith("." + domain):
            return host
    raise EgressRefused(
        f"§19.3: {host!r} is not on the egress allowlist (Charter C12). "
        f"Allowed: {', '.join(allowed_domains(conn)) or '(nothing)'}"
    )


# --- §27.1 autonomy gate ------------------------------------------------------

_AUTONOMY_COLUMNS = {
    "public_web_read": "public_web_read_enabled",
    "browser_control": "browser_control_enabled",
    "external_publish": "external_publish_enabled",
    "external_message": "external_message_enabled",
    "real_spending": "real_spending_enabled",
}


def autonomy_enabled(conn: sqlite3.Connection, flag: str) -> bool:
    column = _AUTONOMY_COLUMNS.get(flag)
    if column is None:
        raise ToolError(f"unknown autonomy flag {flag!r}")
    row = conn.execute(f"SELECT {column} AS v FROM operator_state WHERE id = 1").fetchone()
    return bool(row["v"]) if row is not None else False



#: Charter C14. Anything shaped like a credential is stripped before an error
#: is persisted, exactly as `providers.py` does with provider error text.
_REDACTIONS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|token)\s*[:=]\s*\S+"),
)


def _redact(text: str) -> str:
    for pattern in _REDACTIONS:
        text = pattern.sub("[REDACTED]", text)
    return text[:2_000]



def observations_for(
    conn: sqlite3.Connection, cell_id: str, *, limit: int = 3
) -> list[dict[str, Any]]:
    """Successful tool results for one Cell, most recent first.

    A **read**, not an execution — this is what `context.py` calls, and the
    reason context may import this module at all. There is deliberately no
    path from here back into `execute_grant`.
    """
    rows = conn.execute(
        """
        SELECT tool, arguments_json, source, retrieved_at_utc, licence,
               commercial_use, contains_personal_data, taint_label,
               result_text, result_bytes
        FROM tool_calls
        WHERE cell_id = ? AND status = 'succeeded'
        ORDER BY finished_at_utc DESC
        LIMIT ?
        """,
        (cell_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
