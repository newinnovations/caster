from __future__ import annotations

import curses
import unittest

from caster.app import CTRL_LEFT, CTRL_RIGHT, _read_key


class FakeWindow:
    def __init__(self, keys: bytes) -> None:
        self.keys = iter(keys)
        self.timeouts: list[int] = []

    def getch(self) -> int:
        return next(self.keys, -1)

    def timeout(self, delay: int) -> None:
        self.timeouts.append(delay)


class KeyReaderTests(unittest.TestCase):
    def test_arrow_and_control_arrow_sequences(self) -> None:
        cases = (
            (b"\x1b[D", curses.KEY_LEFT),
            (b"\x1b[C", curses.KEY_RIGHT),
            (b"\x1b[1;5D", CTRL_LEFT),
            (b"\x1b[5D", CTRL_LEFT),
            (b"\x1b[1;5C", CTRL_RIGHT),
            (b"\x1b[5C", CTRL_RIGHT),
        )
        for sequence, expected in cases:
            with self.subTest(sequence=sequence):
                window = FakeWindow(sequence)
                self.assertEqual(_read_key(window), expected)
                self.assertEqual(window.timeouts, [100, 500])


if __name__ == "__main__":
    unittest.main()
