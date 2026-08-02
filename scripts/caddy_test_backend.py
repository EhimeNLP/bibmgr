"""Minimal body-consuming HTTP server for Caddy deployment checks."""

from __future__ import annotations

from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class BodySinkHandler(BaseHTTPRequestHandler):
    """Consume the declared request body before returning an empty response."""

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        remaining = max(0, content_length)
        while remaining:
            chunk = self.rfile.read(min(remaining, 65_536))
            if not chunk:
                return
            remaining -= len(chunk)
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_arguments: object) -> None:
        return


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", arguments.port), BodySinkHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
