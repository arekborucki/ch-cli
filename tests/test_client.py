import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ch_cli.cli import main
from ch_cli.client import Client, QueryError
from ch_cli.config import Profile


class FakeClickHouse(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._reply(200, b"Ok.\n")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        FakeClickHouse.seen.append({"body": body, "params": params, "headers": self.headers})
        if "boom" in body:
            self.send_response(500)
            self.send_header("X-ClickHouse-Exception-Code", "62")
            self.end_headers()
            self.wfile.write(b"Code: 62. DB::Exception: Syntax error")
            return
        self._reply(200, b"" if "empty" in body else b'{"x":1}\n')

    def _reply(self, status, payload):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def server():
    FakeClickHouse.seen = []
    httpd = HTTPServer(("127.0.0.1", 0), FakeClickHouse)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def client(url):
    return Client(Profile(name="t", url=url, user="u", password="pw", database="db"))


def test_ping(server):
    assert client(server).ping() == "Ok."


def test_query_sends_credentials_in_headers_and_settings_in_params(server):
    assert client(server).query("SELECT 1") == '{"x":1}\n'
    req = FakeClickHouse.seen[0]
    assert req["body"] == "SELECT 1"
    assert req["headers"]["X-ClickHouse-User"] == "u"
    assert req["headers"]["X-ClickHouse-Key"] == "pw"
    assert req["params"]["default_format"] == "JSONEachRow"
    assert req["params"]["database"] == "db"
    assert req["params"]["log_comment"].startswith("ch-cli/")
    assert "pw" not in str(req["params"])


def test_query_error_carries_code(server):
    with pytest.raises(QueryError) as e:
        client(server).query("boom")
    assert e.value.code == "62"
    assert "Syntax error" in str(e.value)


def test_unreachable_server():
    with pytest.raises(QueryError, match="cannot reach"):
        Client(Profile(name="t", url="http://127.0.0.1:9", user="u", password=""), timeout=2).ping()


def test_cli_empty_result_says_no_rows_only_in_human_mode(server, monkeypatch, capsys):
    monkeypatch.setenv("CH_CLI_CONFIG", "/nonexistent")
    assert main(["--url", server, "-H", "sql", "empty"]) == 0
    out = capsys.readouterr()
    assert (out.out, out.err) == ("", "(no rows)\n")
    assert main(["--url", server, "sql", "empty"]) == 0
    assert capsys.readouterr() == ("", "")


def test_cli_human_format_and_exit_codes(server, monkeypatch, capsys):
    monkeypatch.setenv("CH_CLI_CONFIG", "/nonexistent")
    assert main(["--url", server, "-H", "sql", "SELECT 1"]) == 0
    assert FakeClickHouse.seen[-1]["params"]["default_format"] == "PrettyCompactMonoBlock"
    assert main(["--url", server, "sql", "boom"]) == 1
    assert "Syntax error" in capsys.readouterr().err
