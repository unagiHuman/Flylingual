"""Explicit Windows real-Player/Brain/API lifecycle verification; no motor or microphone input."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import psutil

from windows_native import ROOT, assert_ports_free, owner_alive, scrubbed_environment

PORTS = [18766, 18770, 18771]


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def verify(mode, directory):
    assert_ports_free(PORTS)
    directory.mkdir(parents=True, exist_ok=False)
    player = ROOT / "artifacts/windows-native-conversation/unity/FlylingualConversation.exe"
    command = [str(player), "-flyConversationNoMicrophone", "-screen-fullscreen", "0",
               "-screen-width", "1280", "-screen-height", "720", "-playScreenProbe", str(directory),
               "-logFile", str(directory / "player.log")]
    if mode == "normal":
        command.append("-playScreenProbeQuit")
    # Neither -flyConversation nor -flyRepoRoot nor the .cmd launcher is used.
    # An unrelated cwd also checks repository discovery from the installed exe.
    process = subprocess.Popen(command, cwd=directory, env=scrubbed_environment(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    identities = {process.pid: psutil.Process(process.pid).create_time()}
    start = time.monotonic()
    peak_rss = 0
    run = None
    report = None
    forced = False
    service_pids = set()
    exit_at = None
    result = {"mode": mode, "playerPid": process.pid, "directExe": True, "microphone": False}

    def track():
        nonlocal peak_rss
        for pid, created in list(identities.items()):
            if not owner_alive(pid, created):
                continue
            try:
                for child in psutil.Process(pid).children(recursive=True):
                    identities.setdefault(child.pid, child.create_time())
            except psutil.Error:
                pass
        rss = 0
        for pid, created in identities.items():
            if owner_alive(pid, created):
                try:
                    rss += psutil.Process(pid).memory_info().rss
                except psutil.Error:
                    pass
        peak_rss = max(peak_rss, rss)

    try:
        while time.monotonic() - start < 90:
            track()
            report = read_json(directory / "report.json")
            if report and report.get("runDirectory"):
                run = Path(report["runDirectory"])
            if run is None:
                for path in (ROOT / "artifacts/windows-native-runs").glob("*/status.json"):
                    status = read_json(path)
                    if status and status.get("ownerPid") == process.pid:
                        run = path.parent
                        break
            status = read_json(run / "status.json") if run else None
            if mode == "startup-crash" and status and not forced:
                psutil.Process(process.pid).kill()
                forced = True
                exit_at = time.monotonic()
            elif mode in ("player-crash", "helper-crash") and report and not forced:
                if mode == "player-crash":
                    psutil.Process(process.pid).kill()
                else:
                    helper = status.get("helperPid") if status else None
                    if helper not in identities or not owner_alive(helper, identities[helper]):
                        raise RuntimeError("Helper identity not observed")
                    helper_process = psutil.Process(helper)
                    service_pids = {helper} | {p.pid for p in helper_process.children(recursive=True)}
                    for parent in helper_process.parents():
                        if parent.pid == process.pid:
                            break
                        service_pids.add(parent.pid)
                    psutil.Process(helper).kill()
                forced = True
                exit_at = time.monotonic()
            if mode == "helper-crash" and forced:
                # Unity's own crash reporter survives while Player is alive;
                # it is not part of the helper's Bridge/Brain service subtree.
                services = [pid for pid, created in identities.items()
                            if pid in service_pids and owner_alive(pid, created)]
                if not services:
                    result["helperCrashServicesStoppedSeconds"] = round(time.monotonic() - exit_at, 3)
                    # End this test's remaining Player only after observing Job cleanup.
                    process.kill()
            if process.poll() is not None:
                exit_at = exit_at or time.monotonic()
                break
            time.sleep(.1)
        if process.poll() is None:
            raise TimeoutError("Player lifecycle probe timed out")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            track()
            remaining = [pid for pid, created in identities.items() if owner_alive(pid, created)]
            if not remaining:
                break
            time.sleep(.1)
        listeners = sorted({c.laddr.port for c in psutil.net_connections(kind="tcp")
                            if c.status == psutil.CONN_LISTEN and c.laddr.port in PORTS})
        report = read_json(directory / "report.json") or report
        samples = report.get("samples", []) if report else []
        frames = [s for s in samples if s["sequence"] >= 0]
        started_live = any(s.get("conversationLive") and s.get("receivedAudioBytes", 0) > 0
                           and s.get("transcriptDeltas", 0) > 0 for s in samples)
        progressed = len({s["sequence"] for s in frames}) > 1
        result.update(exitCode=process.poll(), remainingOwnedPids=remaining, listeningPorts=listeners,
                      cleanupSeconds=round(time.monotonic() - exit_at, 3), peakTreeRssBytes=peak_rss,
                      wallSeconds=round(time.monotonic() - start, 3), automaticGptLive=started_live,
                      sequenceProgressed=progressed, sampledFrames=len(samples),
                      firstSequence=frames[0]["sequence"] if frames else None,
                      lastSequence=frames[-1]["sequence"] if frames else None,
                      states=sorted({s["state"] for s in samples}),
                      backend=sorted({s["backend"] for s in frames}),
                      readyValues=sorted({s["ready"] for s in frames}),
                      protocolErrors=sorted({s["error"] for s in samples if s.get("error")}),
                      runDirectory=str(run) if run else None)
        result["pass"] = (not remaining and not listeners and run is not None
                          and (mode == "startup-crash" or (started_live and progressed and not result["protocolErrors"])))
    finally:
        # Failure cleanup is limited to positively observed identities from this run.
        for pid, created in reversed(list(identities.items())):
            if owner_alive(pid, created):
                try:
                    psutil.Process(pid).kill()
                except psutil.Error:
                    pass
        (directory / "lifecycle.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    return result["pass"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("normal", "player-crash", "startup-crash", "helper-crash"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows required")
    return 0 if verify(args.mode, args.output.resolve()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
