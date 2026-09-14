"""Voice packaging contracts only; no API, Brain or Unity execution."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Runtime.Bridge.config import _DEFAULT, _validate, ConfigError
from Runtime.Bridge.live_webrtc import PCMBuffer, _make_track
from tools.package_judge import configurations, validate_public, assemble
from tools.windows_native import apply_build_selection

ENDPOINT = 'https://judge.example/api/fly/translate'


class VoicePackageTests(unittest.TestCase):
    def test_voice_public_configuration(self):
        bridge, native = configurations(ENDPOINT, voice=True)
        validate_public(bridge)
        validate_public(native)
        self.assertEqual(bridge['conversation']['mode'], 'live')
        self.assertEqual(bridge['conversation']['voiceSessionUrl'], 'https://judge.example/api/fly/voice/session')
        self.assertNotIn('keyFile', native)
        merged = copy.deepcopy(_DEFAULT)
        merged['conversation'].update(bridge['conversation'])
        _validate(merged)

    def test_voice_url_rejects_credentials_wrong_path_and_cleartext(self):
        for url in ('http://judge.example/api/fly/voice/session',
                    'https://user:pass@judge.example/api/fly/voice/session',
                    'https://judge.example/api/fly/voice/session?key=anything',
                    'https://judge.example/api/fly/translate',
                    'https://judge.example/api/fly/voice/session#fragment'):
            with self.subTest(url=url):
                config = copy.deepcopy(_DEFAULT)
                config['conversation'].update(mode='live', voiceSessionUrl=url,
                                               voiceAccessFile='Runtime/Config/voice-access.txt')
                with self.assertRaises(ConfigError):
                    _validate(config)

    def selection(self, conversation, provider):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'
            source.write_text(json.dumps({'conversation': conversation}), encoding='utf-8')
            selection = root / 'build-channel.json'
            selection.write_text(json.dumps({'channel': 'Judge', 'provider': provider,
                                             'backendUrl': ENDPOINT}), encoding='utf-8')
            stack = {'bridgeLocalConfig': str(source), 'keyFile': 'unchanged-direct-key-path'}
            result = apply_build_selection(stack, selection, root / 'status.json')
            return result, json.loads(Path(result['bridgeLocalConfig']).read_text(encoding='utf-8'))

    def test_cloud_build_preserves_voice_mode_and_removes_key_requirement(self):
        bridge, _ = configurations(ENDPOINT, voice=True)
        result, config = self.selection(bridge['conversation'], 'Cloud')
        self.assertEqual(config['conversation']['mode'], 'live')
        self.assertTrue(config['conversation']['voiceSessionUrl'])
        self.assertNotIn('keyFile', result)

    def test_direct_live_local_remains_direct(self):
        result, config = self.selection({'mode': 'live', 'model': 'gpt-live-1'}, 'Local')
        self.assertEqual(config['conversation']['mode'], 'live')
        self.assertEqual(result['keyFile'], 'unchanged-direct-key-path')
        self.assertFalse(config['conversation'].get('voiceSessionUrl'))

    def test_text_cloud_remains_key_free_text(self):
        bridge, _ = configurations(ENDPOINT)
        result, config = self.selection(bridge['conversation'], 'Cloud')
        self.assertEqual(config['conversation']['mode'], 'text')
        self.assertNotIn('keyFile', result)

    def test_provider_key_rejected_before_any_assembly_or_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = root / 'input.txt'
            access.write_text('sk-test-not-a-real-provider-credential', encoding='utf-8')
            with patch('tools.package_judge.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'scoped Flylingual voice access'):
                    assemble(root / 'absent-output', root / 'absent-python', ENDPOINT, access)
                run.assert_not_called()
            self.assertFalse((root / 'absent-output').exists())


class RealAudioFrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_av_frame_pcm_clock_and_layout(self):
        try:
            from aiortc import AudioStreamTrack
            from av import AudioFrame
        except ImportError:
            self.skipTest('optional aiortc/av unavailable')
        buffer = PCMBuffer()
        pcm = b'\x01\x00' * 480
        buffer.append(base64.b64encode(pcm).decode())
        track = _make_track(AudioStreamTrack, AudioFrame, buffer)
        try:
            frame = await track.recv()
            self.assertEqual(frame.samples, 480)
            self.assertEqual(frame.sample_rate, 24000)
            self.assertEqual(frame.format.name, 's16')
            self.assertEqual(frame.layout.name, 'mono')
            self.assertEqual(bytes(frame.planes[0]), pcm)
            following = await track.recv()
            self.assertEqual(following.pts - frame.pts, 480)
        finally:
            track.stop()


if __name__ == '__main__':
    unittest.main()
