"""Real Windows Brain/Responses/Unity distance acceptance, no microphone or fake motion."""
import argparse
import json
import re
import statistics
import subprocess
import time
from pathlib import Path
import psutil
from windows_native import ROOT, Owned, assert_ports_free, bridge_settings, owner_alive, read_stack, scrubbed_environment
from verify_native_voice import collect_hashes, runtime_versions, sha256

def bridge_evidence(config, started, ended):
    """Keep only bounded diagnostic fields from this owned run, never full neural arrays."""
    path = (ROOT/Path(config['logPath'])).resolve()
    events, frames = [], []
    for candidate in (path, Path(str(path)+'.1'), Path(str(path)+'.2')):
        if not candidate.exists(): continue
        with candidate.open(encoding='utf-8') as source:
            for line in source:
                try: row = json.loads(line)
                except ValueError: continue
                if not started*1000 <= row.get('monotonicMs', -1) <= ended*1000: continue
                if row.get('event') == 'frame':
                    frame = row.get('frame', {})
                    frames.append({'at': row['monotonicMs'], 'sequence': frame.get('sequence'),
                                   'stepMs': frame.get('performance', {}).get('stepWallTimeMs')})
                elif row.get('event') in ('command_submitted', 'command_applied', 'execution_ended',
                                          'execution_updated', 'output_inhibited', 'brain_identity'):
                    events.append({k:row[k] for k in ('event', 'monotonicMs', 'reason', 'requestId', 'action',
                        'e2eMs', 'sequence', 'targetDistanceMeters', 'traveledMeters', 'remainingMeters',
                        'distancePhase', 'stopTrigger', 'backendId', 'sessionId', 'sourceHash', 'configHash', 'graphHash') if k in row})
    frames.sort(key=lambda f:f['at']); events.sort(key=lambda e:e['monotonicMs'])
    steps = [f['stepMs'] for f in frames if isinstance(f['stepMs'], (int, float))]
    gaps = [b['at']-a['at'] for a,b in zip(frames,frames[1:])]
    latencies = [e['e2eMs'] for e in events if 'e2eMs' in e]
    return {'frameCount': len(frames), 'firstSequence': frames[0]['sequence'] if frames else None,
            'lastSequence': frames[-1]['sequence'] if frames else None,
            'maxFrameGapMs': max(gaps, default=None), 'stepMedianMs': statistics.median(steps) if steps else None,
            'stepMaxMs': max(steps, default=None), 'appliedMedianMs': statistics.median(latencies) if latencies else None,
            'appliedMaxMs': max(latencies, default=None), 'events': events}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path, default=ROOT/'artifacts/windows-native-conversation/unity/FlylingualConversation.exe')
    parser.add_argument('--short', action='store_true')
    args = parser.parse_args()
    output = (ROOT/args.output).resolve()
    output.relative_to((ROOT/'artifacts').resolve())
    exe = (ROOT/args.exe).resolve()
    config = bridge_settings(read_stack(ROOT/'Runtime/Config/windows-stack.local.json'))
    ports = [config['brain']['port'], config['bridge']['tcpPort'], config['bridge']['controlPort']]
    assert_ports_free(ports)
    output.mkdir(parents=True, exist_ok=False)
    hashes = collect_hashes(output/'no-fixture', config, exe)
    hashes.pop('fixtures', None); hashes.pop('fixtureWavs', None)
    for name in ('Runtime/Bridge/server.py', 'Runtime/Bridge/action_plans.py', 'Runtime/Bridge/control.py',
                 'Runtime/Bridge/conversation.py', 'Runtime/Bridge/conversation_prompts.py',
                 'Runtime/Bridge/intent_contract.py', 'Runtime/Bridge/intent_interpreter.py',
                 'UnityProject/Assets/FlyLocomotion/Terrain/FlyTerrainRuntime.cs',
                 'UnityProject/Assets/RuntimeIntegration/Conversation/Client/ConversationSessionController.cs',
                 'UnityProject/Assets/RuntimeIntegration/Conversation/DistanceIntentProbe.cs',
                 'tools/verify_distance_player.py'):
        hashes['source'][name] = sha256(ROOT/name)
    metadata = dict(hashes=hashes, environment=runtime_versions(config), executable=str(exe),
                    scope='real_windows_brain_responses_body_distance', microphoneTested=False, short=args.short,
                    acceptance='movement_and_next_input; distance_accuracy_recorded_separately')
    command = [str(exe), '-flyRepoRoot', str(ROOT), '-flyConversationNoMicrophone',
               '-distanceProbe', str(output), '-screen-fullscreen', '0', '-screen-width', '1280',
               '-screen-height', '800', '-logFile', str(output/'player.log')]
    if args.short: command.append('-distanceProbeShort')
    start = time.monotonic(); peak = 0
    with (output/'stdout.log').open('w', encoding='utf-8') as stdout:
        player = subprocess.Popen(command, cwd=ROOT, env=scrubbed_environment(), stdin=subprocess.DEVNULL,
                                  stdout=stdout, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        owned = Owned(player)
        try:
            while player.poll() is None and time.monotonic()-start < 370:
                owned.refresh(); rss = 0
                for pid, created in owned.identity.items():
                    if owner_alive(pid, created):
                        try: rss += psutil.Process(pid).memory_info().rss
                        except psutil.Error: pass
                peak = max(peak, rss); time.sleep(.25)
            metadata['timeout'] = player.poll() is None
        finally:
            owned.refresh(); owned.stop(); time.sleep(.25); owned.refresh()
    remaining = [p for p, c in owned.identity.items() if owner_alive(p, c)]
    ports_free = True
    try: assert_ports_free(ports)
    except Exception: ports_free = False
    report_file = output/'report.json'
    report = json.loads(report_file.read_text(encoding='utf-8')) if report_file.exists() else {}
    log = (output/'player.log').read_text(encoding='utf-8', errors='replace')
    errors = len(re.findall(r'^[\w.]*Exception:', log, re.MULTILINE))
    metadata['bridgeEvidence'] = bridge_evidence(config, start, time.monotonic())
    passed = report.get('result') == 'pass' and not metadata['timeout'] and not remaining and ports_free and errors == 0
    metadata.update(status='pass' if passed else 'incomplete', report=report, wallSeconds=round(time.monotonic()-start, 3),
                    peakTreeRssBytes=peak, playerExceptionCount=errors, remainingOwnedPids=remaining, portsFreeAfterCleanup=ports_free)
    (output/'runner-metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:metadata[k] for k in ('status','wallSeconds','playerExceptionCount','remainingOwnedPids','portsFreeAfterCleanup')}))
    return 0 if passed else 1

if __name__ == '__main__':
    raise SystemExit(main())
