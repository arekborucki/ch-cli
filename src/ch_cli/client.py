"""Minimal ClickHouse HTTP client: one POST per query, formatting done by the server."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from ch_cli import __version__
from ch_cli.config import Profile


class QueryError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class Client:
    def __init__(self, profile: Profile, timeout: float = 130.0):
        self.profile = profile
        self.timeout = timeout

    def request(self, path: str, body: bytes | None = None, params: dict | None = None) -> str:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.profile.url}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
        # Credentials go in headers, never in the URL (proxies and server logs record URLs).
        req.add_header("X-ClickHouse-User", self.profile.user)
        if self.profile.password:
            req.add_header("X-ClickHouse-Key", self.profile.password)
        req.add_header("User-Agent", f"ch-cli/{__version__}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace").strip()
            raise QueryError(text, e.headers.get("X-ClickHouse-Exception-Code")) from None
        except urllib.error.URLError as e:
            raise QueryError(f"cannot reach {self.profile.url}: {e.reason}") from None

    def ping(self) -> str:
        return self.request("/ping").strip()

    def query(self, sql: str, fmt: str = "JSONEachRow", settings: dict | None = None) -> str:
        params = {"default_format": fmt, "log_comment": f"ch-cli/{__version__}"}
        if self.profile.database:
            params["database"] = self.profile.database
        params.update(settings or {})
        return self.request("/", body=sql.encode(), params=params)
