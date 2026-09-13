# Windows Replay demo

現在の正式プレイ画面は、リポジトリ直下の `Start-UnityConversation.cmd` で起動します。[現在のUnity起動手順](Unity-Startup-Handoff.md)を参照してください。以下は旧Replayデモの履歴であり、記載のUnity版・checkout・Replay実行手順は現在の通常起動には使用しません。

Integrated `main` commit `c0abf753283dc794ab09c29d0828d7fd55e4338a`.
The frozen Shiu/physics baseline remains `89d1791ebdf1633e57cda5150ea43ff47921313a`.
MaleCNS is not part of this demo. The default source is **REPLAY (Shiu recording)**.

## Source and Editor

```powershell
git clone --branch main --single-branch https://github.com/unagiHuman/Flytest.git
cd Flytest
git status
git rev-parse HEAD
Get-Content UnityProject/ProjectSettings/ProjectVersion.txt
```

Use Unity **6000.5.5f1**, revision `d16e074b49fd`. Do not open with another installed
version or merge `feat/malecns-loader`. The existing project uses URP. The original
rig, joints, FootPads, friction and decoder are preserved; the authorized steering
calculation is shared between controller diagnostics and leg targets.
The demo applies `Assets/Config/FlyGameplayPreset.asset` to a runtime config copy:
steering gain 1.5, minimum inner stride scale -.5, gait 1.6 Hz,
adhesion normal .12 / shear .10, attach delay .02 s,
detach threshold 1.25. The source config asset is never mutated.
Existing scenes retain the .15 minimum stride scale; only the gameplay preset
enables signed inner strides. No requestedAction-based correction is used.

```powershell
unity open ./UnityProject --editor-version 6000.5.5f1
```

Open `Assets/VisualDemo/WindowsReplayDemo.unity`. The original scenes under
`Assets/Scenes` remain separate. `FlyBrain > Windows > Create Replay Demo` regenerates
only the new demo from the baseline scene and the exported visual model. Save any
manual demo-scene work separately before regenerating.

## Build and run

```powershell
./tools/Build-WindowsDemo.ps1 -RecreateScene
./tools/Start-Replay.ps1
# Automated evidence run, 30 seconds with screenshot and CSV:
./tools/Start-Replay.ps1 -Action ALL -Capture -QuitAfter 30
# Independent recorded action:
./tools/Start-Replay.ps1 -Action FORWARD -Capture -QuitAfter 6
```

Player: `artifacts/windows/demo/FlyAscent.exe`. Runs write separate logs, CSV and
optional screenshot folders under `artifacts/windows/runs`. These generated files
are excluded from Git. For the unchanged baseline scene, use
`./tools/Build-WindowsDemo.ps1 -Baseline`.

## Replay and controls

The shipped StreamingAssets JSONL is the normalized 110-frame Shiu recording.
Its source is `Contracts/fixtures/shiu_game_brain_controller_frames.jsonl`.
Normalization changes field layout, not recorded values. Run the Python script
and tests in `Contracts/examples/README.md` to verify this property.

The default launch now opens **The Sugar Run**, a short desk expedition. Enter or
Begin starts the game. W/A/D (or arrows) select recorded forward/steering clips;
release selects the recorded STOP clip. R restarts, right-drag orbits the camera,
and the mouse wheel zooms. The goal is the marked sugar circle; falling below the
table ends the run. The game repeats the selected recording. This is offline
playback interaction, not a newly computed brain response.
Very short keyboard taps are held for a minimum of 100 ms so a press and release
in the same render frame are not lost. After that minimum, release selects STOP.
The goal uses the head position (matching the visual source), not the thorax
center; its height gate prevents below-platform or high-airborne proximity wins.

Pass `-Action ALL` to enter the independent benchmark. The ALL clip plays all 110 frames once (about 24.44 seconds using recorded
step wall times), then the existing ReplayMotorSource outputs zero motor.
Action buttons select recorded clips. They do **not** calculate neural responses
or convert Action names into movement. Loop repeats the selected recording and
is explicitly a playback control. Motor authority stays with `BrainFrame.motor`.

- **ALL 6**: start the full recording.
- **RESTART**: reload the demo scene and restore its initial physical state.
- **E-STOP**: remove motor input and pause game time. This is an emergency pause,
  not biological STOP or adhesion detachment. Select a Replay clip or restart to resume.
- **Live TCP**: opt into the existing localhost:8765 client. Replay requires no server.

HUD shows recording/backend mode, Action, recorded sequence, neural rates,
decoded motor, measured adhesion counters and utilization. Missing recording
request IDs and network E2E are N/A. Frame age is local playback age, not Live latency.
The replay is not a successful Windows Live Brain validation.
Per-leg bars show measured `GripUtilization` capped at one for attached feet and
zero for free feet. The uncapped peak load and detach count are also shown. These
are measured load, not invented strength or a biological percentage. The existing
normal-force application uses its configured budget when attached, so normal load
alone can fill a bar. Live TCP and loop configuration remain benchmark controls.

CSV samples link each observed Replay frame to current physical displacement/yaw.
If rendering skips recording indices, a warning and skippedFrames counter preserve
that missingness; body positions for missed frames are never interpolated as measurements.

## Visual and stage

`ArtSource/Blender/FlyVisual.blend` is the local original-body model, exported as FBX.
See its README for provenance and regeneration. The scene adds 18 separately mapped
visual leg segments, six visual-only proximal bridges, rest-offset/endpoint calibration,
thin bristles and toe details. VisualRig
has no Collider, Rigidbody or ArticulationBody and never writes to the physical rig.
Materials are recreated for URP, including double-sided transparent wing membranes.

The desk stage contains books, a cup, can, keys, sugar and a narrow elevated ledge. It is
a compact gameplay course. Only measured traversal is an acceptance result;
the presence of high scenery does not certify climbing it. Adhesion uses the single
gameplay preset above; root forces and artificial falling teleports are not added.
Some idle distal FootPads remain above the floor in the frozen physical pose;
visual endpoint agreement does not make that contact behavior complete.
The first route crosses a broad 2-degree notebook ramp to an .08-unit summit and
the sugar goal. Keyboard props were moved away from the legs' swept path after
an actual stalled trial. Later high props are scenery, not a validated tall-wall
climbing route. A small 17 Hz / .65-degree wing vibration is visual-only.

`-courseTrial goal` enables a test driver that chooses the same W/A/D recorded
inputs based on observed heading. It cannot move the body or alter BrainFrame
values. Normal launches never enable it. `-courseTrial fall` tests driving off the
table and scene reload. Each trial writes pose, inputs, real contact and grip logs.

## Shiu Live

See [SHIU_WINDOWS.md](SHIU_WINDOWS.md) for the tested native environment, dependency
provenance, compiler failure and separate dataset gate. The independent environment
is `artifacts/windows-shiu/.venv`. Data belongs at the exact paths in that document
and must match the Mac data manifest. Do not copy conda, Cython caches or MaleCNS data.

## Troubleshooting

- Missing Editor: install the exact version, keeping other versions side by side.
- Program Files permission denied: install under a user-writable path, then restore
  the former default install path and explicitly register this Editor if needed.
- Keep the Editor install path short. The first install under the nested workspace
  omitted long URP filenames (over 260 characters), causing package compiler errors.
  Use a short folder such as `C:/Users/tiger/UnityEditors/6000.5.5f1`, and pass
  `-EditorPath <full Unity.exe path>` to the build script when needed.
- Missing fixture: recreate the demo so the normalized fixture is copied to StreamingAssets.
- Replay shows N/A: inspect the normalized input; do not fill unknown neural values with zero.
- Live disconnected/stale: verify server READY and localhost:8765; do not extend stale
  timeout to hide latency. Use only one controlling client.
- Cython `io.h` missing: install the Windows SDK as documented; NumPy fallback is not a pass.

Actual results and remaining limitations are recorded in `windows_validation_report.md`.
