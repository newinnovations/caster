from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from caster.media import inspect_media


class WebMCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not shutil.which("ffprobe"):
            raise unittest.SkipTest(
                "ffmpeg and ffprobe are required for WebM media tests"
            )

        encoder_result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
        )
        encoder_names = {
            fields[1]
            for line in f"{encoder_result.stdout}\n{encoder_result.stderr}".splitlines()
            if len(fields := line.split()) > 1
        }
        required_encoders = {"libvpx", "libvpx-vp9", "libvorbis"}
        if not required_encoders <= encoder_names:
            raise unittest.SkipTest("FFmpeg lacks VP8, VP9, or Vorbis encoders")

        cls.directory = tempfile.TemporaryDirectory()
        cls.samples: dict[str, Path] = {}
        for codec, encoder in (("vp8", "libvpx"), ("vp9", "libvpx-vp9")):
            path = Path(cls.directory.name) / f"sample-{codec}.webm"
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=640x360:r=30",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:sample_rate=48000",
                    "-t",
                    "1",
                    "-c:v",
                    encoder,
                    "-deadline",
                    "realtime",
                    "-cpu-used",
                    "8",
                    "-b:v",
                    "500k",
                    "-c:a",
                    "libvorbis",
                    "-y",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            cls.samples[codec] = path

    @classmethod
    def tearDownClass(cls) -> None:
        directory = getattr(cls, "directory", None)
        if directory is not None:
            directory.cleanup()

    def test_vp8_webm_with_vorbis_is_accepted(self) -> None:
        media = inspect_media(self.samples["vp8"])
        self.assertEqual(media.video_codec, "vp8")
        self.assertEqual(media.content_type, "video/webm")
        self.assertEqual(media.audio_codecs, ("vorbis",))

    def test_vp9_webm_with_vorbis_is_accepted(self) -> None:
        media = inspect_media(self.samples["vp9"])
        self.assertEqual(media.video_codec, "vp9")
        self.assertEqual(media.video_profile, "Profile 0")
        self.assertEqual(media.content_type, "video/webm")
        self.assertEqual(media.audio_codecs, ("vorbis",))


if __name__ == "__main__":
    unittest.main()
