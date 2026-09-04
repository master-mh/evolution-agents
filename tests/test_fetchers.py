"""fetchers.py's egress boundary: the transport that actually opens the
socket (implementation brief, Slice B).

test_charter_properties.py's C12 property test checks the domain *string*
allowlist. It cannot see a robots.txt redirect, a hang, an oversized
response, or a hostname that resolves somewhere the allowlist never
considered -- those only show up once something actually listens on a
socket. These tests run real local HTTP servers for exactly that reason
(the brief's own reproduction of the redirect bug used two of them).
"""

from __future__ import annotations

import http.server
import threading
import time

import pytest

from mitosis import fetchers
from mitosis.tool_registry import ToolError

_HANG = object()


class _Server:
    """A throwaway HTTP server on 127.0.0.1:<free port>, one thread per request.

    `routes` maps a path to (status, body, headers) or the `_HANG` sentinel,
    which accepts the connection and never responds. `hits` records every
    path actually requested -- the thing most of these tests exist to check
    is what was *not* requested.
    """

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.hits: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                outer.hits.append(self.path)
                route = outer.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if route is _HANG:
                    time.sleep(30)
                    return
                status, body, headers = route
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if body:
                    self.wfile.write(body)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def server_factory(monkeypatch):
    # Every test server here is necessarily on loopback, which the SSRF guard
    # (added below) now correctly refuses on its own -- these tests are about
    # robots/redirect/timeout handling, not the guard, so bypass it here. The
    # guard itself is tested directly, unpatched, further down.
    monkeypatch.setattr(fetchers, "_check_destination_safe", lambda hostname: None)

    servers: list[_Server] = []

    def make(routes: dict[str, object]) -> _Server:
        server = _Server(routes)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


def test_a_redirected_robots_txt_destination_is_never_contacted(server_factory):
    """The brief's own reproduction: an allowlisted-shaped host 302s its
    robots.txt to a second host. Under the old `RobotFileParser.read()` path
    the second host was contacted and its (attacker-controlled) policy
    accepted; refusing the redirect must mean the fetch fails closed instead."""
    decoy = server_factory({"/anything": (200, b"should never be served", None)})
    origin = server_factory(
        {
            "/robots.txt": (302, b"", {"Location": f"{decoy.base_url}/anything"}),
            "/page": (200, b"hello", None),
        }
    )

    fetcher = fetchers.UrlLibFetcher()
    with pytest.raises(ToolError, match="robots.txt disallows"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)

    assert decoy.hits == []


def test_a_redirected_page_destination_is_never_contacted(server_factory):
    decoy = server_factory({"/anything": (200, b"should never be served", None)})
    origin = server_factory(
        {
            "/robots.txt": (200, b"", None),
            "/page": (302, b"", {"Location": f"{decoy.base_url}/anything"}),
        }
    )

    fetcher = fetchers.UrlLibFetcher()
    with pytest.raises(ToolError, match="redirect"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)

    assert decoy.hits == []


def test_a_hanging_robots_endpoint_times_out(server_factory, monkeypatch):
    monkeypatch.setattr(fetchers, "TIMEOUT_SECONDS", 1)
    origin = server_factory({"/robots.txt": _HANG, "/page": (200, b"hello", None)})

    fetcher = fetchers.UrlLibFetcher()
    started = time.monotonic()
    with pytest.raises(ToolError, match="robots.txt disallows"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"took {elapsed:.1f}s — the timeout did not fire"


def test_an_oversized_robots_response_is_refused(server_factory):
    huge = b"# padding\n" * (fetchers.MAX_ROBOTS_BYTES // 8)
    assert len(huge) > fetchers.MAX_ROBOTS_BYTES
    origin = server_factory({"/robots.txt": (200, huge, None), "/page": (200, b"hello", None)})

    fetcher = fetchers.UrlLibFetcher()
    with pytest.raises(ToolError, match="robots.txt disallows"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)


def test_robots_401_disallows(server_factory):
    origin = server_factory({"/robots.txt": (401, b"", None), "/page": (200, b"hi", None)})
    fetcher = fetchers.UrlLibFetcher()
    with pytest.raises(ToolError, match="robots.txt disallows"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)


def test_robots_403_disallows(server_factory):
    origin = server_factory({"/robots.txt": (403, b"", None), "/page": (200, b"hi", None)})
    fetcher = fetchers.UrlLibFetcher()
    with pytest.raises(ToolError, match="robots.txt disallows"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)


def test_robots_404_means_nothing_is_restricted(server_factory):
    origin = server_factory({"/page": (200, b"hi", None)})  # no /robots.txt route -> 404
    fetcher = fetchers.UrlLibFetcher()
    result = fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)
    assert result.text == "hi"


def test_robots_disallow_all_disallows(server_factory):
    origin = server_factory(
        {
            "/robots.txt": (200, b"User-agent: *\nDisallow: /\n", None),
            "/page": (200, b"hi", None),
        }
    )
    fetcher = fetchers.UrlLibFetcher()
    with pytest.raises(ToolError, match="robots.txt disallows"):
        fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)


def test_robots_empty_body_allows(server_factory):
    origin = server_factory({"/robots.txt": (200, b"", None), "/page": (200, b"hi", None)})
    fetcher = fetchers.UrlLibFetcher()
    result = fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)
    assert result.text == "hi"


def test_a_connection_failure_is_not_permission(monkeypatch):
    """§19.4 asks for robots.txt compliance. Where it cannot be determined
    (DNS failure, connection refused, reset), the safe reading is the
    restrictive one -- a fetcher that treated an unreachable robots.txt as
    consent would be claiming compliance it does not have.

    Mocks the opener itself rather than `RobotFileParser.read` (the old
    target, before this slice): `_robots_allow` no longer calls `.read()` at
    all, so a mock there would silently stop testing anything."""
    fetcher = fetchers.UrlLibFetcher()

    def boom(*_args, **_kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(fetcher._opener, "open", boom)
    assert fetcher._robots_allow("https://example.test/x") is False


def test_a_fetched_page_records_personal_data_status_as_unknown_not_no(server_factory):
    """§20.1/§20.2: the fetcher has performed no classification, so writing
    `False` was always a fabricated negative. `unknown` is the honest value
    -- see the module docstring."""
    origin = server_factory({"/robots.txt": (200, b"", None), "/page": (200, b"hi", None)})
    fetcher = fetchers.UrlLibFetcher()
    result = fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)
    assert result.contains_personal_data == "unknown"
    assert result.contains_personal_data != "no"


def test_respect_robots_false_skips_the_check_entirely(server_factory):
    origin = server_factory(
        {
            "/robots.txt": (200, b"User-agent: *\nDisallow: /\n", None),
            "/page": (200, b"hi", None),
        }
    )
    fetcher = fetchers.UrlLibFetcher(respect_robots=False)
    result = fetcher.fetch(f"{origin.base_url}/page", max_bytes=1000)
    assert result.text == "hi"


# --- _check_destination_safe: a hostname on the allowlist is not a promise
# about the address it resolves to ---------------------------------------------


def test_a_loopback_destination_is_refused_before_any_connection():
    """The positive case for the whole guard, deliberately not using
    `server_factory` (which bypasses this exact check for its own,
    unrelated tests): a real local server runs on loopback, and the fetch
    must be refused without ever contacting it."""
    server = _Server({"/page": (200, b"hi", None)})
    try:
        fetcher = fetchers.UrlLibFetcher()
        with pytest.raises(ToolError, match="not a public address"):
            fetcher.fetch(f"{server.base_url}/page", max_bytes=1000)
        assert server.hits == []
    finally:
        server.close()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "127.0.0.53",  # loopback, non-standard address in the /8
        "::1",  # loopback, IPv6
        "10.1.2.3",  # private
        "172.16.0.5",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local -- the AWS/GCP/Azure/Alibaba metadata IP
        "169.254.1.1",  # link-local
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "fc00::1",  # unique local, IPv6's private range
        "fe80::1",  # link-local, IPv6
        "ff02::1",  # multicast, IPv6
    ],
)
def test_check_destination_safe_refuses_every_non_public_range(address, monkeypatch):
    monkeypatch.setattr(
        fetchers.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, "", (address, 0))]
    )
    with pytest.raises(ToolError, match="not a public address"):
        fetchers._check_destination_safe("whatever.test")


def test_check_destination_safe_allows_a_public_address(monkeypatch):
    monkeypatch.setattr(
        fetchers.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, "", ("8.8.8.8", 0))]
    )
    fetchers._check_destination_safe("whatever.test")  # does not raise


def test_check_destination_safe_refuses_if_any_resolved_address_is_unsafe(monkeypatch):
    """A hostname that resolves to multiple addresses (round-robin DNS, or a
    dual-stack A + AAAA answer) is refused if even one of them is unsafe --
    the caller has no control over which address `urllib` picks to connect
    to next."""
    monkeypatch.setattr(
        fetchers.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (None, None, None, "", ("8.8.8.8", 0)),
            (None, None, None, "", ("127.0.0.1", 0)),
        ],
    )
    with pytest.raises(ToolError, match="not a public address"):
        fetchers._check_destination_safe("whatever.test")


def test_check_destination_safe_wraps_a_resolution_failure(monkeypatch):
    def boom(*_a, **_k):
        raise fetchers.socket.gaierror("nope")

    monkeypatch.setattr(fetchers.socket, "getaddrinfo", boom)
    with pytest.raises(ToolError, match="could not resolve"):
        fetchers._check_destination_safe("whatever.test")
