"""A small, dependency-free HTTP service around the pipeline.

    GET  /healthz              liveness + playbook fingerprint + engine version
    POST /v1/decisions         one thread (JSON) -> decision record
    POST /v1/decisions:batch   {"threads": [...]} -> {"results": [...]}

The pipeline is stateless, so this can run behind any WSGI/ASGI gateway or be re-implemented in FastAPI
without touching the engine. Supplier text is never logged.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .domain import InvalidThreadError, ThreadInput
from .pipeline import DecisionPipeline

log = logging.getLogger("procurement_desk.service")
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_BATCH = 1000


def make_server(pipeline: DecisionPipeline, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"procurement-desk/{__version__}"

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise InvalidThreadError("request body missing or too large")
            try:
                return json.loads(self.rfile.read(length))
            except json.JSONDecodeError as error:
                raise InvalidThreadError(f"invalid JSON: {error}") from error

        def do_GET(self) -> None:                       # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"status": "ok", "engine_version": __version__,
                                 "playbook_fingerprint": pipeline.playbook.fingerprint})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:                      # noqa: N802
            try:
                if self.path == "/v1/decisions":
                    record = pipeline.decide(ThreadInput.from_mapping(self._read_json()))
                    self._send(200, record.to_dict())
                elif self.path == "/v1/decisions:batch":
                    body = self._read_json()
                    rows = body.get("threads") if isinstance(body, dict) else None
                    if not isinstance(rows, list) or not rows or len(rows) > MAX_BATCH:
                        raise InvalidThreadError(f"'threads' must be a list of 1..{MAX_BATCH} items")
                    self._send(200, {"results": [pipeline.decide(ThreadInput.from_mapping(r)).to_dict() for r in rows]})
                else:
                    self._send(404, {"error": "not found"})
            except InvalidThreadError as error:
                self._send(400, {"error": str(error)})
            except Exception:                           # noqa: BLE001
                log.exception("unhandled error")
                self._send(500, {"error": "internal error"})

        def log_message(self, fmt: str, *args: Any) -> None:    # access log without payloads
            log.info("%s %s", self.address_string(), fmt % args)

    return ThreadingHTTPServer((host, port), Handler)
