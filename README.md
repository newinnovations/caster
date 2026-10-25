# Caster

Cast a local video file to a Chromecast from a terminal. Caster serves the original file over HTTP with byte-range support for seeking; it never re-encodes or changes the media.

## Requirements

- Python 3.12 and `uv`
- `ffprobe` from FFmpeg on `PATH`
- A Chromecast on the same LAN; the Chromecast must be able to connect to this computer on the port Caster opens

Install the project environment and command:

```sh
uv sync
uv run caster --help
```

## Run

```sh
uv run caster video.mp4
uv run caster video.mp4 --device 192.168.1.42
uv run caster video.mp4 --device chromecast.local
```

Without `--device`, Caster discovers devices, uses the sole device automatically, or prompts when several are found. It exits if no device is found. `--device` accepts an IPv4 address or hostname.

Check a file without connecting to a Chromecast:

```sh
uv run caster video.mp4 --check-only
```

The compatibility check accepts H.264 in MP4/M4V (Baseline/Constrained Baseline through level 3.1, Main through 4.0, High through 4.1), plus VP8 or VP9 in WebM. VP8 is capped at 1080p30 or 720p60; VP9 accepts Profiles 0 and 2 up to 4K/60. MP4 audio may be AAC-LC, HE-AAC, or MP3; WebM audio may be Vorbis or Opus. VP9 support and maximum resolution vary by Chromecast model, so a passing check cannot guarantee playback on every receiver. See [Google's supported media table](https://developers.google.com/cast/docs/media). Unsupported files are rejected rather than transcoded.

## YouTube helper

`cast-yt.sh` downloads a YouTube video and then casts it with Caster:

```sh
./cast-yt.sh 'https://www.youtube.com/watch?v=VIDEO_ID'
```

It accepts `youtube.com/watch?v=...` URLs (with or without `www`) and `youtu.be/...` links with an 11-character video ID. The script stores videos in `./videos/<video-id>.webm`; it prefers VP9 video with Opus audio up to 2160p, then falls back to the best format up to 2160p. If that file already exists, it skips downloading and casts the existing file. On the first needed download it installs `yt-dlp` under `./tools`; later needed downloads update it. `curl` and an internet connection are needed to fetch `yt-dlp` and videos. The script runs `uv run caster`, so install the project environment with `uv sync` first.

## Controls

- `Space`: play/pause
- `Left` / `Right`: seek 30 seconds backward/forward
- `Ctrl+Left` / `Ctrl+Right`: seek 5 minutes backward/forward
- `0`–`9`: jump to 0%–90% of the timeline
- `q` or `Ctrl-C`: stop casting and quit
