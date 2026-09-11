# MaleCNS Windows Replay integration — 2026-09-11

Status: parser / metadata / HUD pass; full Replay gate remains provisional.

Tested source: `253a1ec9eda78a14873999325bbe7d697918f715`, containing Mac handoff
`2992c0c` and implementation `9cbad4e`. The remote already merged the Mac feature.
Windows fetched and detached at that commit; local main remains `bc62c01`.
No local main merge, branch creation, commit or push was performed for this test.
The repository root corresponds to the handoff's `Parallel/`; there is no nested Parallel directory.

Unity 6000.5.5f1. Original frozen Shiu Player hashes still match `replay_freeze.json`.
Integration builds are separate at `artifacts/windows/m1/player/FlyAscent.exe`.
Editor compilation and Standalone build passed; build logs are `m1-build.log` and
`m1-warmup-build.log` under `artifacts/windows/`.

## Wire and parser

Fixture: `Contracts/fixtures/malecns_game_brain_controller_frames_wire_v1.jsonl`.
SHA256 `d7638ff329e02b9d050570a69e67ce5678a01604bce06c3882a90ce5cfcb6e57`.
76 frames: STOP 36, each of the five moving actions 8. No fixture edits.
Original JsonUtility motor/performance/requestedAction/sequence parsing succeeds.
Additive DTO fields retain metadata and VNC readout that previously were ignored.
Actual Unity-deserialized output is compared against the source by
`tools/verify_malecns_replay.py` (float tolerance 2e-6 relative / 1e-7 absolute).
Both MaleCNS 76 and Shiu 110 pass this comparison. Unknown fields remain ignorable.
Metadata is MALECNS_EXPERIMENTAL / MaleCNS + Shiu-compatible LIF /
VNC_ANALOG_POPULATION / ready=false on every MaleCNS frame.

The last four frames of each moving segment have the expected forward/turn signs.
STOP recovery segments contain residual output; each reaches zero at its last frame.
These transient values are retained, not corrected by action labels.

## Physical observations

Each moving clip was selected from the unchanged recording and repeated using the
existing ReplayMotorSource. Tests use the frozen gain 1.5 / minimum side scale -.5
and adhesion preset. Physics, CPG and decoder sources were not edited.
Each trial settles for 100 physics ticks and then resets CPG phase; small initial
pose differences still occur in PhysX, so exact deterministic pose equality is not claimed.
Unwrapped yaw over common 501-step / 10.000086 second windows:

| Action | yaw change |
|---|---:|
| FORWARD | +43.34 degrees |
| TURN_R | +56.71 degrees |
| TURN_L | -14.83 degrees |
| FORWARD_R | +200.08 degrees |
| FORWARD_L | -46.64 degrees |

FORWARD moved forward (net z about +.67 over the complete trial), but rightward yaw
bias is substantial. Directions of the four turning clips are correct, their
magnitudes are not balanced. This is not a gameplay acceptance pass.
Per-tick raw/CPG motor, joint targets, yaw rate, pose and grip are in
`artifacts/windows/m1/<ACTION>/steering.csv`; summary is `steering-summary.json`.

The STOP clip-selection test concatenates six distinct recovery segments, with
nonzero residuals from different preceding actions. It is **not** a sustained STOP
response and must not be used to claim Live stop latency or failure. The uncut
76-frame recording is the valid causal order. This also limits using arbitrary
MaleCNS clip selection as the finished game input mode.

## HUD and frame observation

Player screenshot `artifacts/windows/m1/male-all/demo.png` was inspected:
MALECNS REPLAY, model, VNC readout identity, ready=false, action, neural fields,
motor and grip fit on screen. VNC delta mV values come from the frame; no inferred activity.

Initial un-warmed runs observed 69/76 (six initial frames unobserved, one later gap).
They remain preserved. Initial process wait also expired during startup/shutdown;
Player subsequently exited normally. Shiu regression observed 110/110, zero gaps.
Optional `-demoWarmup` waits for 60 rendered Update frames before restarting the
recording at its first frame, without changing any recorded duration or motor value.
Final warmup observation results are recorded in `M1-malecns-replay-results.json`.
MaleCNS finished 76/76 with zero gaps; Shiu finished 110/110 with zero gaps.
All integration Player logs contain zero managed exception matches. The moving
clip trials used the first integration build; the final build only adds optional
warmup, which those trials do not enable. Their first-build evidence is retained.

Reproduce from repository root (Unity CLI on PATH):

```powershell
unity run UnityProject --editor-version 6000.5.5f1 --timeout 1800 -- -executeMethod WindowsDemoBuilder.BuildMaleCnsIntegration -buildTarget Win64
$fixture = (Resolve-Path Contracts/fixtures/malecns_game_brain_controller_frames_wire_v1.jsonl).Path
& ./artifacts/windows/m1/player/FlyAscent.exe -demoReplay $fixture -demoAction ALL -demoWarmup -demoQuitAfter 45 -demoOutput ./artifacts/windows/m1/reproduce
python tools/verify_malecns_replay.py
```

## Changes and remaining gate

- BrainProtocol.cs: additive serializable metadata/readout DTOs, no existing field changes.
- WindowsReplayDemo.cs: optional absolute `-demoReplay` input, metadata-aware HUD,
  optional benchmark warmup. Existing default remains Shiu.
- WindowsDemoBuilder.cs: parser verification and separate integration build entry point.
- tools/verify_malecns_replay.py and these validation reports/results.

No SerializeField changes, scene/prefab/config edits, MaleCNS model/decoder edits,
locomotion changes or action-specific physical corrections.
Replay gate remains provisional pending sustained STOP / arbitrary-input semantics
and forward-bias acceptance. Live gate must not start until this is resolved.
