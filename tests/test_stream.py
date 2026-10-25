from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from caster.stream import MediaServer


class MediaServerRangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.media_path = Path(self.directory.name) / "clip.mp4"
        self.media_path.write_bytes(b"0123456789abcdef")
        self.server = MediaServer(self.media_path, "127.0.0.1", "video/mp4")

    def tearDown(self) -> None:
        self.server.close()
        self.directory.cleanup()

    def test_range_request_returns_requested_bytes_and_headers(self) -> None:
        request = Request(self.server.url, headers={"Range": "bytes=3-6"})
        with urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 3-6/16")
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.headers["Content-Type"], "video/mp4")
            self.assertEqual(response.read(), b"3456")

    def test_webm_is_served_with_video_webm_content_type(self) -> None:
        server = MediaServer(self.media_path, "127.0.0.1", "video/webm")
        try:
            with urlopen(server.url) as response:
                self.assertEqual(response.headers["Content-Type"], "video/webm")
                self.assertTrue(server.url.endswith("/video.webm"))
        finally:
            server.close()

    def test_suffix_range_returns_final_bytes(self) -> None:
        request = Request(self.server.url, headers={"Range": "bytes=-4"})
        with urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 12-15/16")
            self.assertEqual(response.read(), b"cdef")

    def test_unsatisfiable_range_returns_416(self) -> None:
        request = Request(self.server.url, headers={"Range": "bytes=16-"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 416)
        self.assertEqual(raised.exception.headers["Content-Range"], "bytes */16")


if __name__ == "__main__":
    unittest.main()
