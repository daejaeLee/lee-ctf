#!/usr/bin/env python3
"""Deterministic local HTTP target for harness tests; never exposes a live secret."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    secret = "CTF{mock_only_candidate}"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size) or b"{}")
        prompt = str(payload.get("message", ""))
        normalized = prompt.lower().replace(" ", "")
        if "flag" in normalized and "prefix" not in normalized:
            response: object = {"response": "I cannot reveal a complete secret."}
        elif "prefix:ctf{" in normalized:
            response = {"response": "yes"}
        elif "tool" in normalized:
            response = {"tool": {"name": "mock_search", "arguments": {"q": "safe"}}, "response": "tool selected"}
        elif "showsecret" in normalized:
            response = {"response": Handler.secret}
        else:
            response = {"response": "baseline"}
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
