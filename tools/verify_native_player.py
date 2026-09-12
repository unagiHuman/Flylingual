"""Explicit Windows real-Player/API probe. Never supplies microphone or motor samples."""
import argparse
import asyncio
import aiohttp
import json
from pathlib import Path
import subprocess
import time
import psutil

from windows_native import ROOT, Owned, scrubbed_environment, owner_alive

async def second_control_rejected():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
        try:
            async with session.ws_connect('http://127.0.0.1:18771/ws', compress=0):
                return False
        except aiohttp.WSServerHandshakeError as exc:
            return exc.status == 409
        except (aiohttp.ClientError, TimeoutError):
            return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=1, choices=range(1, 6))
    args = parser.parse_args()
    output = ROOT / 'artifacts/windows-native-conversation' / time.strftime('validation-%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for cycle in range(1, args.cycles + 1):
        path = output / f'cycle-{cycle}.json'
        command = [str(ROOT / 'artifacts/windows-native-conversation/unity/FlylingualConversation.exe'),
                   '-flyRepoRoot', str(ROOT), '-flyConversationProbe', '-flyConversationProbeQuit',
                   '-flyConversationProbeOutput', str(path), '-logFile', str(output / f'player-{cycle}.log'),
                   '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '800']
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=ROOT, env=scrubbed_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        owned = Owned(process)
        peak_rss = 0
        rejected = None
        while process.poll() is None and time.monotonic() - started < 140:
            owned.refresh()
            if rejected is None and path.with_suffix('.png').is_file():
                rejected = asyncio.run(second_control_rejected())
            rss = 0
            for pid, created in owned.identity.items():
                if owner_alive(pid, created):
                    try: rss += psutil.Process(pid).memory_info().rss
                    except psutil.Error: pass
            peak_rss = max(peak_rss, rss)
            time.sleep(.25)
        timeout = process.poll() is None
        if timeout:
            owned.stop()
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            remaining = [pid for pid, created in owned.identity.items() if owner_alive(pid, created)]
            if not remaining:
                break
            time.sleep(.25)
        report = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'result': 'missing_probe'}
        report.update(cycle=cycle, timeout=timeout, exitCode=process.poll(), remainingOwnedPids=remaining,
                      secondControlRejected=rejected,
                      peakTreeRssBytes=peak_rss, wallSeconds=round(time.monotonic()-started, 3))
        results.append(report)
        print(json.dumps(report), flush=True)
        (output / 'summary.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        if remaining:
            owned.stop()  # Only this cycle's positively identified processes.
        if report['result'] != 'transport_audio_pass' or remaining or timeout or rejected is not True:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
