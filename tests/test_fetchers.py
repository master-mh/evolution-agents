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
def server_factory():
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
