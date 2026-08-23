"""The one module that actually opens a socket (SPEC.md §19.3, §19.4, §20).

Kept separate from `tool_registry` and `tools` on purpose: nothing in the
kernel imports this, and `tools.execute_grant` defaults to `RefusingFetcher`.
§19.3 ships "network disabled by default", and a default that quietly worked
would mean the test suite could make real requests without anyone choosing
that. Reaching the network is an explicit act — `mitosis run-tool --live`.

**Redirects are refused, not followed, and this is the important line in the
file.** Charter C12's allowlist is checked against the URL a human approved.
`urllib` follows redirects by default, so a page on an allowlisted domain that
answers `302 https://anywhere.example/` would carry the fetch straight off the
allowlist — the check would have passed and the request would land somewhere
nobody approved. That is not a hypothetical: an open redirect on an otherwise
reputable allowlisted host is enough. Refusing the redirect turns it into a
failed call the Cell may *propose* to follow explicitly, which puts the
destination back in front of a human, which is the whole design.

**§20.1's metadata is reported as unknown rather than guessed.** A web fetch
cannot determine a licence, and §20.2 is explicit that public visibility does
not imply the right to store, resell, or train on something. `unknown` is the
honest value and forces the question to be answered by a person before any
commercial use; a fetcher that wrote `permitted` would be manufacturing a
rights position the colony does not have.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse, urlunparse

from .tool_registry import FetchResult, ToolError

#: Identifies the colony to the sites it reads (§19.4's "source provenance"
#: obligation, pointed the other way — a host should be able to tell who is
#: asking and block it).
USER_AGENT = "MitosisColony/0.2 (autonomous research agent; read-only)"

#: §19.3 runtime limit.
TIMEOUT_SECONDS = 20


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Turn any redirect into a refusal. See the module docstring."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolError(
            f"refused to follow a {code} redirect to {newurl!r}: the egress "
            "allowlist was checked against the approved URL, and following a "
            "redirect would reach a host nobody approved (Charter C12). "
            "Propose fetching that URL explicitly instead."
        )


class UrlLibFetcher:
    """A minimal, read-only HTTP GET.

    Deliberately not a browser and deliberately not a crawler: it fetches one
    URL, follows nothing, and executes no scripts. §19.4 forbids unrestricted
    crawling, and `autonomy.browser_control` is a separate flag with no tool
    behind it precisely so that "read a page" and "drive a browser" cannot be
    granted by the same decision.
    """

    def __init__(self, *, respect_robots: bool = True) -> None:
        self.respect_robots = respect_robots
        self._opener = urllib.request.build_opener(_NoRedirects())

    def fetch(self, url: str, *, max_bytes: int) -> FetchResult:
        if self.respect_robots and not self._robots_allow(url):
            # §19.4: "robots.txt compliance where applicable". A refusal, not a
            # warning — a colony that logged this and proceeded would be
            # claiming compliance it does not have.
            raise ToolError(f"robots.txt disallows fetching {url!r}")

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                # Read one byte past the cap so truncation is detectable rather
                # than silent — a result cut at exactly the limit is
                # indistinguishable from one that happened to fit.
                raw = response.read(max_bytes + 1)
                status = response.status
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as exc:
            # A definite, unambiguous rejection by the server: nothing was
            # delivered, so this is a failure rather than an unknown outcome.
            raise ToolError(f"HTTP {exc.code} for {url!r}") from exc

        text = raw[:max_bytes].decode(charset, errors="replace")
        return FetchResult(
            text=text,
            http_status=status,
            source=url,
            # §20.1/§20.2 — see the module docstring on why these are unknown.
            licence="unknown",
            permitted_uses="review only; no storage, redistribution or training",
            commercial_use="unknown",
            contains_personal_data=False,
        )

    def _robots_allow(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except Exception:
            # An unreadable robots.txt is not permission. §19.4 asks for
            # compliance "where applicable"; where it cannot be determined,
            # the safe reading is the restrictive one.
            return False
        return parser.can_fetch(USER_AGENT, url)
