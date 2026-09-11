# Replay game progress — 2026-09-11

Base: main `c0abf753283dc794ab09c29d0828d7fd55e4338a`. Unity 6000.5.5f1.
This update advances the game shell and presentation. It does not certify a
finished climbing game or a working Windows Live backend.

## Delivered

- Default Player launch: The Sugar Run, with start, timer, goal distance, goal,
  fall and restart states. A finite desk surrounds an open route to sugar;
  books/cup/can/keyboard and an elevated ledge remain stage props.
- W/A/D or arrows select real recorded clips; key release selects recorded STOP.
  The sidebar also selects clips. Motor authority stays with ReplayMotorSource.
  Right-drag orbits, wheel zooms, R reloads the scene. Focus loss selects STOP.
- Per-foot attached/free indicators and remaining grip-margin bars use existing
  diagnostics. No attachment percentage or force is fabricated.
- A camera facing the course, compact numeric neural readouts, denser compound
  eye facets, and the existing transparent wings/body hairs/18-joint visual mapping.
- Blender MCP addon installed and Codex entry registered. Localhost socket scene
  query succeeded; current-task MCP tool hot reload is pending. See ArtSource README.

## Verification

- `artifacts/windows/game-build-final.log`: build exit 0, no C# errors;
  `GAME_RULES_PASS` for spawn, goal, fall, height separation and outside radius.
  These are synthetic rule checks, not physical course completion.
- Builder compares all physical rig articulation/collider/config serialization
  before and after presentation changes: unchanged. Visual physics components: 0.
- Frozen 52 source/assets/settings files: SHA-256 unchanged.
- `python -m unittest discover -s tools -p test_normalize_shiu_replay.py`: 6 pass.
- Player `artifacts/windows/runs/20260911-123604-857`: 110/110 recorded frames,
  0 skipped, all 6 actions, 0 motor/neural value mismatches, no managed exceptions.
  Render frame-time p95 16.6816 ms; fixed step about .02 s. These are not brain
  step or network E2E timings. Max visual endpoint error 5.9921e-7 world units.
- Native Player UI: Enter starts; recorded FORWARD visibly moves the six-legged
  visual; R returns to the start screen and resets time/location. Verified on
  input-fixed build before final display/camera-only changes.
- Final game run `runs/20260911-123730-580`: course-facing camera and compact HUD
  visually inspected, Enter and wheel zoom checked through native Player input,
  no managed exception observed. Player remains open for user testing.
- Initial runtime check exposed disabled legacy Input API. Fixed through IMGUI
  key/mouse events without changing global input handling or adding packages.
  Original failing log retained at `runs/20260911-122959-808/Player.log`.

Sequential measured yaw deltas: TURN_R +10.635°, TURN_L −3.979°, FORWARD_R
+16.114°, FORWARD_L +0.129°. FORWARD_L therefore still fails the expected left
sign gate. Do not label the complete six-action physical baseline as passed.
CSV/summary: `artifacts/windows/game-replay-summary.json`. STOP spans multiple
intervals; its aggregate displacement is not an isolated STOP trial.

## Remaining game acceptance

Actual full-course completion and a natural fall-to-restart sequence have not
been demonstrated. Higher climbing obstacles and contact realism remain
unfinished. The inherited physical pose can leave feet off the desk; measured
adhesion is currently zero in these samples. This update does not tune CPG,
friction, FootPads, joints, adhesion or decoder, and adds no root steering force.
The next game task is to establish controllable traversal on this short course
before expanding the ascent.

Shiu dependency imports and server help still pass. Windows SDK/UCRT and the
verified v783 data/manifest remain missing. MaleCNS code/data/server were not used.

## Run

```powershell
./tools/Start-Replay.ps1
# independent six-action benchmark
./tools/Start-Replay.ps1 -Action ALL -Capture -QuitAfter 30
```

Changes remain local and uncommitted. Generated Players/logs/caches are ignored.
