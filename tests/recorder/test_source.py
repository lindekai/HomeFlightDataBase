import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from recorder.source import fetch_aircraft


class LocalHTTPServer(HTTPServer):
    """Ohne Reverse-DNS-Abfrage beim Binden (``getfqdn`` kann je nach Netz lange blockieren)."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture
def server():
    responses = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = responses.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = LocalHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", responses
    httpd.shutdown()


def test_valid_json(server):
    base, responses = server
    responses["/ok"] = json.dumps({"now": 1.0, "aircraft": []}).encode()
    assert fetch_aircraft(base + "/ok") == {"now": 1.0, "aircraft": []}


def test_invalid_inputs_return_none(server):
    base, responses = server
    responses["/bad"] = b"{not json"
    responses["/nonow"] = b'{"aircraft": []}'
    assert fetch_aircraft(base + "/bad") is None
    assert fetch_aircraft(base + "/nonow") is None
    assert fetch_aircraft(base + "/missing") is None
    assert fetch_aircraft("http://127.0.0.1:1/unreachable", timeout=0.5) is None
