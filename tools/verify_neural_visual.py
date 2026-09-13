"""Observe real Windows Brain firing and rendered pixels in the normal Player.

The explicit probe sends one finite text movement request through Responses.
No microphone, fabricated activity, direct motor values or second Brain client.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import psutil

from windows_native import (ROOT, Owned, assert_ports_free, bridge_settings,
                            owner_alive, read_stack, scrubbed_environment)
from verify_native_voice import sha256, runtime_versions, collect_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    output.relative_to((ROOT / 'artifacts').resolve())
    output.mkdir(parents=True, exist_ok=False)
    config = bridge_settings(read_stack(ROOT / 'Runtime/Config/windows-stack.local.json'))
    ports = [config['brain']['port'], config['bridge']['tcpPort'], config['bridge']['controlPort']]
    assert_ports_free(ports)
    exe = ROOT / 'artifacts/windows-native-conversation/unity/FlylingualConversation.exe'
    # Reuse exact runtime/config/data provenance, without implying fixture input.
    hashes = collect_hashes(output / 'no-fixture-input', config, exe)
    hashes.pop('fixtures', None)
    hashes.pop('fixtureWavs', None)
    for path in ('UnityProject/Assets/BrainVisualization/Rendering/NeuralPointCloud.cs',
                 'UnityProject/Assets/BrainVisualization/Rendering/NeuralPointCloud.shader',
                 'UnityProject/Assets/BrainVisualization/Runtime/NeuralActivityObserver.cs',
                 'UnityProject/Assets/BrainVisualization/Runtime/NeuralVisualizationPanel.cs',
                 'UnityProject/Assets/RuntimeIntegration/PlayScreen/PlayScreenView.cs',
                 'UnityProject/Assets/RuntimeIntegration/PlayScreen/PlayScreenProbe.cs',
                 'tools/verify_neural_visual.py'):
        hashes['source'][path] = sha256(ROOT / path)
    metadata = {'hashes': hashes, 'environment': runtime_versions(config),
                'scope': 'real_brain_text_command_neural_render', 'microphoneTested': False}
    command = [str(exe), '-flyRepoRoot', str(ROOT), '-flyConversationNoMicrophone',
               '-playScreenProbe', str(output), '-playScreenProbeMove', '-playScreenProbeQuit',
               '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '800',
               '-logFile', str(output / 'player.log')]
    started = time.monotonic()
    peak_rss = 0
    with (output / 'stdout.log').open('w', encoding='utf-8') as stdout:
        player = subprocess.Popen(command, cwd=ROOT, env=scrubbed_environment(),
                                  stdout=stdout, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        owned = Owned(player)
        try:
            while player.poll() is None and time.monotonic() - started < 110:
                owned.refresh()
                rss = 0
                for pid, created in owned.identity.items():
                    if owner_alive(pid, created):
                        try: rss += psutil.Process(pid).memory_info().rss
                        except psutil.Error: pass
                peak_rss = max(peak_rss, rss)
                time.sleep(.25)
            metadata['timeout'] = player.poll() is None
        finally:
            owned.refresh()
            owned.stop()
            time.sleep(.25)
            owned.refresh()
    remaining = [pid for pid, created in owned.identity.items() if owner_alive(pid, created)]
    ports_free = True
    try: assert_ports_free(ports)
    except Exception: ports_free = False
    report_path = output / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    errors = len(re.findall(r'^[\w.]*Exception:', (output / 'player.log').read_text(encoding='utf-8', errors='replace'), re.MULTILINE))
    passed = bool(report.get('movementRequested') and report.get('positiveSpikeSamples', 0) > 0
                  and report.get('positiveVoltageSamples', 0) > 0 and report.get('maxCyanPixels', 0) > 0
                  and report.get('maxWarmPixels', 0) > 0 and not report.get('visualError')
                  and not metadata['timeout'] and not remaining and ports_free and errors == 0 and player.returncode == 0)
    metadata.update(status='pass' if passed else 'incomplete', probe=report,
                    exitCode=player.returncode, remainingOwnedPids=remaining,
                    portsFreeAfterCleanup=ports_free, playerExceptionCount=errors,
                    wallSeconds=round(time.monotonic() - started, 3), peakTreeRssBytes=peak_rss)
    (output / 'runner-metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: metadata[key] for key in ('status', 'remainingOwnedPids', 'portsFreeAfterCleanup')}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
