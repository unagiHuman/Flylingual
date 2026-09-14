"""Packaging freshness checks; no Unity, Brain or API execution."""
import os
from pathlib import Path
import tempfile
import unittest

from tools.package_submission import check_player_freshness


class PlayerFreshnessTests(unittest.TestCase):
    def test_changed_unity_input_requires_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'player/FlylingualConversation_Data/boot.config'
            marker.parent.mkdir(parents=True)
            marker.write_text('build marker')
            asset = root / 'project/Assets/game.cs'
            asset.parent.mkdir(parents=True)
            asset.write_text('source')
            os.utime(marker, (1000, 1000))
            os.utime(asset, (999, 999))
            result = check_player_freshness(root / 'player', root / 'project')
            self.assertEqual(result['newerUnityInputs'], 0)
            os.utime(asset, (1001, 1001))
            with self.assertRaisesRegex(ValueError, 'rebuild Judge / Cloud'):
                check_player_freshness(root / 'player', root / 'project')

    def test_missing_marker_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'marker missing'):
                check_player_freshness(Path(directory), Path(directory))
