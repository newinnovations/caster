from __future__ import annotations

import argparse
import curses
import ipaddress
import socket
import sys
from pathlib import Path
from typing import Any, Sequence

from .media import MediaError, MediaInfo, inspect_media
from .stream import MediaServer, route_local_address


class DeviceError(RuntimeError):
    """Chromecast discovery or selection failed."""


CTRL_LEFT = 1001
CTRL_RIGHT = 1002

_ARROW_KEYS = {
    b"\x1b[D": curses.KEY_LEFT,
    b"\x1b[1D": curses.KEY_LEFT,
    b"\x1bOD": curses.KEY_LEFT,
    b"\x1b[C": curses.KEY_RIGHT,
    b"\x1b[1C": curses.KEY_RIGHT,
    b"\x1bOC": curses.KEY_RIGHT,
    b"\x1b[1;5D": CTRL_LEFT,
    b"\x1b[5D": CTRL_LEFT,
    b"\x1b[1;5C": CTRL_RIGHT,
    b"\x1b[5C": CTRL_RIGHT,
}


def _read_key(stdscr: Any) -> int:
    key = stdscr.getch()
    if key != 27:
        return key

    sequence = bytearray((key,))
    stdscr.timeout(100)
    try:
        while len(sequence) < 16:
            next_key = stdscr.getch()
            if next_key < 0:
                break
            sequence.append(next_key)
            if len(sequence) >= 3 and 0x40 <= next_key <= 0x7E:
                break
    finally:
        stdscr.timeout(500)
    return _ARROW_KEYS.get(bytes(sequence), 27)


def _device_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.gethostbyname(value))
        except (OSError, ValueError) as exc:
            raise DeviceError(
                f"cannot resolve Chromecast host {value!r}: {exc}"
            ) from exc
    if address.version != 4:
        raise DeviceError("Chromecast hostnames must resolve to an IPv4 address")
    return str(address)


def _select_cast(device: str | None) -> tuple[Any, Any]:
    import pychromecast

    requested_address = _device_address(device) if device else None
    known_hosts = [requested_address] if requested_address else None
    casts, browser = pychromecast.get_chromecasts(
        known_hosts=known_hosts, tries=1, timeout=10
    )
    try:
        if not casts:
            if requested_address:
                raise DeviceError(
                    f"no Chromecast found at {device} ({requested_address})"
                )
            raise DeviceError("no Chromecast devices found on the network")
        if requested_address:
            selected = next(
                (cast for cast in casts if cast.cast_info.host == requested_address),
                None,
            )
            if selected is None:
                raise DeviceError(
                    f"no Chromecast found at {device} ({requested_address})"
                )
        elif len(casts) == 1:
            selected = casts[0]
        else:
            print("Multiple Chromecast devices found:", file=sys.stderr)
            for index, cast in enumerate(casts, start=1):
                print(
                    f"  {index}. {cast.name} ({cast.cast_info.host})", file=sys.stderr
                )
            try:
                choice = int(input(f"Select a device [1-{len(casts)}]: "))
            except (EOFError, ValueError) as exc:
                raise DeviceError(
                    "choose a device number or pass --device HOST"
                ) from exc
            if not 1 <= choice <= len(casts):
                raise DeviceError(
                    f"device selection must be between 1 and {len(casts)}"
                )
            selected = casts[choice - 1]
        selected.wait(timeout=10)
    except BaseException:
        try:
            browser.stop_discovery()
        except Exception:
            pass
        raise
    return selected, browser


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def _position(cast: Any) -> float:
    status = cast.media_controller.status
    try:
        current_time = status.adjusted_current_time
        if current_time is None:
            current_time = status.current_time
        return max(0.0, float(current_time or 0.0))
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _player_state(cast: Any) -> str:
    try:
        return str(cast.media_controller.status.player_state or "Loading")
    except AttributeError:
        return "Loading"


def _seek(cast: Any, target: float, duration: float) -> None:
    cast.media_controller.seek(min(duration, max(0.0, target)))


def _init_colors() -> dict[str, int]:
    styles = {
        "normal": 0,
        "frame": 0,
        "header": 0,
        "accent": 0,
        "selected": 0,
        "filled": 0,
        "empty": 0,
    }
    try:
        if not curses.has_colors():
            return styles
        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLUE)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        curses.init_pair(4, curses.COLOR_BLUE, curses.COLOR_CYAN)
        bright = curses.A_BOLD
        styles.update(
            normal=curses.color_pair(1) | bright,
            frame=curses.color_pair(2) | bright,
            header=curses.color_pair(1) | bright,
            accent=curses.color_pair(3) | bright,
            selected=curses.color_pair(4) | bright,
            filled=curses.color_pair(4) | bright,
            empty=curses.color_pair(2) | bright,
        )
    except curses.error:
        return {name: 0 for name in styles}
    return styles


def _put(stdscr: Any, row: int, column: int, text: str, style: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if row < 0 or row >= height or column < 0 or column >= width - 1:
        return
    stdscr.addnstr(row, column, text, width - column - 1, style)


def _draw_progress(
    stdscr: Any,
    row: int,
    width: int,
    current: float,
    duration: float,
    styles: dict[str, int],
) -> None:
    if width < 8:
        return
    ratio = min(1.0, max(0.0, current / duration)) if duration > 0 else 0.0
    percent = int(ratio * 100)
    bar_width = width - 7
    filled = min(bar_width, int(ratio * bar_width))
    _put(stdscr, row, 2, "[", styles["frame"])
    _put(stdscr, row, 3, "#" * filled, styles["filled"])
    _put(stdscr, row, 3 + filled, "." * (bar_width - filled), styles["empty"])
    _put(stdscr, row, 3 + bar_width, "]", styles["frame"])
    _put(stdscr, row, 4 + bar_width, f" {percent:3d}%", styles["accent"])


def _draw(stdscr: Any, cast: Any, media: MediaInfo, styles: dict[str, int]) -> None:
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    if width < 3 or height < 4:
        stdscr.refresh()
        return

    right = width - 2
    bottom = height - 2
    _put(stdscr, 0, 0, "┌" + "─" * (right - 1) + "┐", styles["frame"])
    _put(stdscr, bottom, 0, "└" + "─" * (right - 1) + "┘", styles["frame"])
    for row in range(1, bottom):
        _put(stdscr, row, 0, "│", styles["frame"])
        _put(stdscr, row, right, "│", styles["frame"])
    if height < 12:
        _put(stdscr, 1, 2, "CASTER", styles["header"])
        stdscr.refresh()
        return

    content_width = max(0, right - 3)
    _put(stdscr, 1, 2, "CASTER", styles["header"])
    if bottom > 2:
        _put(stdscr, 2, 0, "├" + "─" * (right - 1) + "┤", styles["frame"])

    current = min(max(0.0, media.duration), _position(cast))
    state = _player_state(cast)
    footer = bottom - 1
    if height >= 20:
        _put(stdscr, 3, 2, "NOW PLAYING", styles["accent"])
        _put(stdscr, 4, 2, media.path.name, styles["header"])
        _put(stdscr, 5, 2, f"Receiver: {cast.name}", styles["normal"])
        _put(stdscr, 6, 2, f"State: {state}", styles["accent"])
        audio = ", ".join(media.audio_codecs) if media.audio_codecs else "none"
        video_label = (
            "H.264" if media.video_codec == "h264" else media.video_codec.upper()
        )
        if media.video_profile:
            video_label += f" {media.video_profile}"
        _put(
            stdscr,
            7,
            2,
            f"Video: {video_label}, {media.width}x{media.height} at "
            f"{media.frame_rate:g} fps; audio: {audio}",
            styles["normal"],
        )
        if bottom > 8:
            _put(stdscr, 8, 0, "├" + "─" * (right - 1) + "┤", styles["frame"])
        _put(stdscr, 9, 2, "TIMELINE", styles["accent"])
        _put(
            stdscr,
            10,
            2,
            f"{_format_time(current)} / {_format_time(media.duration)}",
            styles["normal"],
        )
        _draw_progress(stdscr, 11, content_width, current, media.duration, styles)
        if bottom > 12:
            _put(stdscr, 12, 0, "├" + "─" * (right - 1) + "┤", styles["frame"])
        _put(stdscr, 13, 2, "PLAYBACK CONTROLS", styles["accent"])
        _put(stdscr, 14, 2, "Space       Play / pause", styles["normal"])
        _put(stdscr, 15, 2, "Left/Right  Seek 30 seconds", styles["normal"])
        _put(
            stdscr,
            16,
            2,
            "Ctrl+Arrows Seek 5 minutes   0-9 Jump to 0%-90%",
            styles["normal"],
        )
    else:
        _put(stdscr, 3, 2, media.path.name, styles["header"])
        _put(stdscr, 4, 2, f"State: {state}", styles["accent"])
        _put(
            stdscr,
            5,
            2,
            f"{_format_time(current)} / {_format_time(media.duration)}",
            styles["normal"],
        )
        _draw_progress(stdscr, 6, content_width, current, media.duration, styles)
        if footer > 7:
            _put(stdscr, 7, 2, "Space Play/Pause   Arrows Seek", styles["normal"])
    _put(stdscr, footer, 1, " " * (right - 1), styles["selected"])
    _put(
        stdscr, footer, 2, "Space Play/Pause   Q Stop   Ctrl-C Quit", styles["selected"]
    )

    stdscr.refresh()


def _run_tui(cast: Any, media: MediaInfo) -> None:
    def interact(stdscr: Any) -> None:
        stdscr.keypad(False)
        stdscr.timeout(500)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        styles = _init_colors()
        try:
            stdscr.bkgd(" ", styles["normal"])
        except curses.error:
            pass

        while True:
            _draw(stdscr, cast, media, styles)
            key = _read_key(stdscr)
            if key in (-1,):
                continue
            if key in (ord("q"), ord("Q"), 3):
                return
            if key == ord(" "):
                if _player_state(cast) == "PLAYING":
                    cast.media_controller.pause()
                else:
                    cast.media_controller.play()
            elif key == curses.KEY_LEFT:
                _seek(cast, _position(cast) - 30, media.duration)
            elif key == curses.KEY_RIGHT:
                _seek(cast, _position(cast) + 30, media.duration)
            elif key == CTRL_LEFT:
                _seek(cast, _position(cast) - 300, media.duration)
            elif key == CTRL_RIGHT:
                _seek(cast, _position(cast) + 300, media.duration)
            elif ord("0") <= key <= ord("9"):
                _seek(cast, media.duration * (key - ord("0")) / 10, media.duration)

    curses.wrapper(interact)


def _stop_cast(cast: Any) -> None:
    try:
        cast.media_controller.stop()
    except Exception:
        pass
    try:
        cast.quit_app()
    except Exception:
        pass
    try:
        cast.disconnect()
    except Exception:
        pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caster",
        description="Cast a compatible local MP4 or WebM to a Chromecast without re-encoding.",
    )
    parser.add_argument("video", type=Path, help="local MP4 or WebM video file")
    parser.add_argument(
        "-d", "--device", metavar="HOST", help="Chromecast IPv4 address or hostname"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="check media compatibility without discovering a Chromecast",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        media = inspect_media(args.video)
    except MediaError as exc:
        print(f"caster: {exc}", file=sys.stderr)
        return 2

    if args.check_only:
        container_name = "WebM" if media.content_type == "video/webm" else "MP4"
        print(
            f"Compatible {container_name}: {media.path} ({media.width}x{media.height}, "
            f"{media.frame_rate:g} fps, {_format_time(media.duration)})"
        )
        return 0

    cast = None
    browser = None
    try:
        cast, browser = _select_cast(args.device)
        address = route_local_address(cast.cast_info.host)
        with MediaServer(media.path, address, media.content_type) as server:
            cast.media_controller.play_media(
                server.url, media.content_type, title=media.path.name
            )
            _run_tui(cast, media)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"caster: {exc}", file=sys.stderr)
        return 1
    finally:
        if cast is not None:
            _stop_cast(cast)
        if browser is not None:
            try:
                browser.stop_discovery()
            except Exception:
                pass
    return 0
