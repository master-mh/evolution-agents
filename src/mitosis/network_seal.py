"""A process-wide seal on network access and child processes while a
synthetic run executes (SPEC.md §7.1 "zero paid model calls", §0.4 "no
network from generated code", §19.3 "network disabled by default"; ADR-085).

**Why this exists.** On 2026-09-09 Anthropic published an assessment of four
incidents in which models under evaluation were *told* they were in a
simulation without internet access, while a configuration error in the outer
evaluation environment left real connectivity available — and the models used
it. The failure was never the instruction; it was that nothing *enforced* it.

The flight simulator makes the same kind of promise. Its manifest reports
`usd_real_spend_unchanged`, and every run so far has honoured that — because
`runner.run` happens to construct `SimulationPolicyProvider`, which happens to
make no call. That is a property of which object is wired in, checked after the
fact. A provider swapped for a real one, a fetcher reached through a tool path,
an epoch hook that shells out: each would reach the outside world first and be
noticed, if at all, in a manifest afterwards. This module makes "a simulated run
cannot reach outside the interpreter" something the interpreter refuses, rather
than something the wiring happens to satisfy — the same move as ADR-047's
foreign key over an injected seam: make the violation unrepresentable instead
of checking for it.

**How.** A PEP 578 audit hook, installed once per process (audit hooks cannot be
removed), raises `NetworkSealed` for the audited events that open a connection,
resolve a name, send a datagram, bind a listener, or start a child process —
but only while at least one `sealed()` block is active. Outside a block the hook
returns immediately, so an ordinary colony, the CLI and the test suite are
unaffected.

**Process-wide, not per-thread, on purpose.** A context variable would not
follow a thread started inside the run, and a thread is the easiest way for a
misconfigured component to escape a per-thread seal. While a run is sealed,
every thread in the process is.

**What this is not: a sandbox.** Audit hooks see the standard library's audited
operations. `ctypes`, a C extension making raw syscalls, or a process started
before the seal can all bypass it. It defends against *misconfiguration* — the
incident class above — and not against adversarial code, which is §19.2's
microVM boundary and Phase 5's job. Stated here so nobody reads a green seal
test as a security boundary.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from typing import Iterator

#: Audited events that reach outside the interpreter. Name resolution is
#: included because a DNS lookup is itself egress (§19.3's "DNS control"),
#: and `bind` because a sealed run has no business accepting connections
#: either. Creating a socket object (`socket.__new__`) is deliberately *not*
#: here: a socketpair inside the interpreter reaches nothing, and refusing it
#: would break unrelated standard-library internals without closing any path.
SEALED_EVENTS = frozenset({
    "socket.connect",
    "socket.bind",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyaddr",
    "socket.getnameinfo",
    "socket.sendto",
    "socket.sendmsg",
    "http.client.connect",
    "urllib.Request",
    "ftplib.connect",
    "smtplib.connect",
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "os.forkpty",
    "webbrowser.open",
})


class NetworkSealed(RuntimeError):
    """A sealed run tried to reach outside the interpreter.

    A `RuntimeError`, not an `OSError`: `urllib` and friends wrap `OSError`
    into their own connection errors, and a refusal disguised as an ordinary
    network failure is exactly what a retry loop would swallow.
    """


_lock = threading.Lock()
_depth = 0
_reasons: list[str] = []
_installed = False


def _hook(event: str, args: tuple) -> None:
    # Checked in this order so the unsealed common case costs one integer test.
    if _depth and event in SEALED_EVENTS:
        raise NetworkSealed(
            f"network sealed ({_reasons[-1] if _reasons else 'sealed run'}): "
            f"refused {event}"
        )


def _install() -> None:
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def is_sealed() -> bool:
    return _depth > 0


@contextmanager
def sealed(*, reason: str) -> Iterator[None]:
    """Refuse every `SEALED_EVENTS` operation in this process until the
    outermost `sealed()` block exits — including when it exits by exception.
    Nests: an inner block ending does not unseal an outer one."""
    global _depth
    with _lock:
        _install()
        _depth += 1
        _reasons.append(reason)
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            _reasons.pop()
