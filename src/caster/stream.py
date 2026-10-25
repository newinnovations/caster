from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast


class _MediaHTTPServer(ThreadingHTTPServer):
    media_path: Path
    content_length: int
    content_type: str
    media_url_path: str

    allow_reuse_address = True
    daemon_threads = True


class _MediaRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self) -> None:
        self._serve(send_body=False)

    def do_GET(self) -> None:
        self._serve(send_body=True)

    def _serve(self, send_body: bool) -> None:
        server = cast(_MediaHTTPServer, self.server)
        if self.path.split("?", 1)[0] != server.media_url_path:
            self.send_error(404)
            return

        size = server.content_length
        requested_range = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if requested_range is not None:
            parsed = self._parse_range(requested_range, size)
            if parsed is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = parsed
            status = 206

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", server.content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return

        try:
            with server.media_path.open("rb") as media_file:
                media_file.seek(start)
                remaining = length
                while remaining:
                    chunk = media_file.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    @staticmethod
    def _parse_range(value: str, size: int) -> tuple[int, int] | None:
        if not value.startswith("bytes=") or "," in value:
            return None
        bounds = value[6:].split("-", 1)
        if len(bounds) != 2:
            return None
        first, last = bounds
        try:
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            elif last:
                suffix_length = int(last)
                if suffix_length <= 0:
                    return None
                start = max(0, size - suffix_length)
                end = size - 1
            else:
                return None
        except ValueError:
            return None
        if start < 0 or start >= size or end < start:
            return None
        return start, min(end, size - 1)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class MediaServer:
    """Serve one local media file to a Chromecast with byte-range seeking."""

    def __init__(self, path: Path, local_address: str, content_type: str) -> None:
        if content_type not in {"video/mp4", "video/webm"}:
            raise ValueError(f"unsupported media type {content_type}")
        self._server = _MediaHTTPServer((local_address, 0), _MediaRequestHandler)
        self._server.media_path = path
        self._server.content_length = path.stat().st_size
        self._server.content_type = content_type
        extension = ".webm" if content_type == "video/webm" else ".mp4"
        self._server.media_url_path = f"/video{extension}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://{local_address}:{self._server.server_port}{self._server.media_url_path}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def __enter__(self) -> MediaServer:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def route_local_address(chromecast_address: str) -> str:
    """Find the local IPv4 interface that can reach the selected Chromecast."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
            route_socket.connect((chromecast_address, 8009))
            local_address = route_socket.getsockname()[0]
    except OSError as exc:
        raise OSError(
            f"cannot determine a network route to Chromecast {chromecast_address}: {exc}"
        ) from exc
    if not local_address or local_address == "0.0.0.0":
        raise OSError(f"no usable local IPv4 route to Chromecast {chromecast_address}")
    return local_address
