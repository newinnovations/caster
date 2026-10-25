from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any


class MediaError(ValueError):
    """The input file cannot be played directly by a Chromecast receiver."""


_H264_MAX_LEVELS = {
    "baseline": 31,
    "constrained baseline": 31,
    "main": 40,
    "high": 41,
}

_MEDIA_CONTAINERS = {
    ".mp4": ("mp4", "video/mp4"),
    ".m4v": ("mp4", "video/mp4"),
    ".webm": ("webm", "video/webm"),
}


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    duration: float
    width: int
    height: int
    frame_rate: float
    video_codec: str
    video_profile: str
    audio_codecs: tuple[str, ...]
    content_type: str


def _frame_rate(stream: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if not value or value == "0/0":
            continue
        try:
            rate = float(Fraction(value))
        except (ValueError, ZeroDivisionError):
            continue
        if math.isfinite(rate) and rate > 0:
            return rate
    raise MediaError("cannot determine the video's frame rate")


def inspect_media(path: Path) -> MediaInfo:
    """Probe and conservatively check supported MP4/WebM without transcoding."""
    try:
        resolved_path = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise MediaError(f"cannot access video file {path}: {exc}") from exc
    if not resolved_path.is_file():
        raise MediaError(f"not a regular video file: {resolved_path}")

    container_info = _MEDIA_CONTAINERS.get(resolved_path.suffix.lower())
    if container_info is None:
        raise MediaError(
            "only MP4/M4V and WebM video files are supported; no re-encoding is performed"
        )
    container_name, content_type = container_info

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,codec_name,profile,level,width,height,avg_frame_rate,r_frame_rate",
        "-of",
        "json",
        str(resolved_path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        metadata = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise MediaError(
            "ffprobe was not found; install FFmpeg and make ffprobe available on PATH"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "ffprobe rejected the file"
        raise MediaError(f"cannot read video metadata: {detail}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MediaError("ffprobe returned invalid media metadata") from exc

    format_names = set(metadata.get("format", {}).get("format_name", "").split(","))
    if container_name not in format_names:
        raise MediaError(
            f"the file is not a {container_name.upper()} container; no re-encoding is performed"
        )

    streams = metadata.get("streams", [])
    video_streams = [
        stream for stream in streams if stream.get("codec_type") == "video"
    ]
    if not video_streams:
        raise MediaError(f"the {container_name.upper()} contains no video stream")
    video = video_streams[0]
    video_codec = str(video.get("codec_name") or "unknown").lower()
    profile = str(video.get("profile") or "").strip()

    if container_name == "mp4" and video_codec == "h264":
        max_level = _H264_MAX_LEVELS.get(profile.lower())
        if max_level is None:
            raise MediaError(
                f"unsupported H.264 profile {profile or 'unknown'}; use Baseline, Main, or High"
            )
        level = video.get("level")
        if not isinstance(level, int) or level <= 0 or level > max_level:
            allowed_level = f"{max_level // 10}.{max_level % 10}"
            raise MediaError(
                f"H.264 level is unknown or above {allowed_level} for profile {profile}; outside this app's conservative Chromecast limits"
            )
    elif container_name == "webm" and video_codec == "vp8":
        if profile and not profile.lower().startswith("profile"):
            profile = f"Profile {profile}"
    elif container_name == "webm" and video_codec == "vp9":
        vp9_profile = profile.lower().removeprefix("profile").strip()
        if vp9_profile not in {"0", "2"}:
            raise MediaError(
                f"unsupported VP9 profile {profile or 'unknown'}; use Profile 0 or Profile 2"
            )
        profile = f"Profile {vp9_profile}"
        level = video.get("level")
        if isinstance(level, int) and level > 51:
            raise MediaError("VP9 level above 5.1 exceeds supported Chromecast limits")
    else:
        supported = "H.264" if container_name == "mp4" else "VP8 or VP9"
        raise MediaError(
            f"unsupported {video_codec} video codec in {container_name.upper()}; use {supported}"
        )

    try:
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaError("cannot determine the video's dimensions") from exc
    if width <= 0 or height <= 0:
        raise MediaError("the video's dimensions are invalid")

    frame_rate = _frame_rate(video)
    if video_codec == "vp9":
        if width * height > 3840 * 2160 or max(width, height) > 3840:
            raise MediaError("VP9 resolution exceeds the 4K Chromecast limit")
        max_frame_rate = 60
    else:
        if width * height > 1920 * 1080 or max(width, height) > 1920:
            raise MediaError(
                "video resolution exceeds the conservative 1080p Chromecast limit"
            )
        max_frame_rate = 60 if min(width, height) <= 720 else 30
    if frame_rate > max_frame_rate:
        raise MediaError(
            f"{frame_rate:g} fps exceeds the {max_frame_rate} fps limit for this resolution"
        )

    audio_streams = [
        stream for stream in streams if stream.get("codec_type") == "audio"
    ]
    audio_codecs: list[str] = []
    for audio in audio_streams:
        codec = audio.get("codec_name")
        if container_name == "mp4" and codec == "aac":
            audio_profile = str(audio.get("profile") or "").lower()
            if audio_profile not in {"lc", "he-aac", "he-aacv2"}:
                raise MediaError(
                    f"unsupported AAC profile {audio.get('profile') or 'unknown'}; use AAC-LC or HE-AAC"
                )
        elif container_name == "mp4" and codec == "mp3":
            pass
        elif container_name == "webm" and codec in {"vorbis", "opus"}:
            pass
        else:
            supported_audio = (
                "AAC-LC, HE-AAC, or MP3"
                if container_name == "mp4"
                else "Vorbis or Opus"
            )
            raise MediaError(
                f"unsupported {container_name.upper()} audio codec {codec or 'unknown'}; use {supported_audio}"
            )
        audio_codecs.append(str(codec))

    try:
        duration = float(metadata["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaError("cannot determine the video's duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("the video has no valid duration")

    return MediaInfo(
        path=resolved_path,
        duration=duration,
        width=width,
        height=height,
        frame_rate=frame_rate,
        video_codec=video_codec,
        video_profile=profile,
        audio_codecs=tuple(audio_codecs),
        content_type=content_type,
    )
