from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from caster.app import _position
from pychromecast.controllers.media import MediaStatus


class PositionTests(unittest.TestCase):
    def _cast_with_status(self, player_state: str) -> SimpleNamespace:
        status = MediaStatus()
        status.current_time = 12.5
        status.playback_rate = 1.5
        status.player_state = player_state
        status.last_updated = datetime.now(timezone.utc) - timedelta(seconds=5)
        return SimpleNamespace(media_controller=SimpleNamespace(status=status))

    def test_playing_position_advances_since_last_receiver_update(self) -> None:
        cast = self._cast_with_status("PLAYING")
        self.assertAlmostEqual(_position(cast), 20.0, delta=0.1)

    def test_paused_position_stays_at_last_reported_time(self) -> None:
        cast = self._cast_with_status("PAUSED")
        self.assertEqual(_position(cast), 12.5)


if __name__ == "__main__":
    unittest.main()
