# Windows validation — 2026-09-11 JST

## Outcome

Windows版Replayデモのビルド・実行と、6 Action／110フレームの再生を確認しました。
Visual・HUD・Stageは動作する初期版です。接地姿勢と段差走破は未完成で、
Shiu LiveはWindows SDKと別送データ待ちです。MaleCNSには変更していません。

Windows Standalone Replay demo builds and runs with the existing physical rig.
All 110 recorded frames / six Actions were observed without skipped frames or
recorded-value mismatches. The visual/HUD/stage are a working prototype, not a
completed realistic locomotion or climbing validation. SHIU LIVE remains blocked
by Windows SDK/UCRT headers and the separately transferred connectome data.
MaleCNS was neither merged nor run.

## Requested report

| Item | Result |
|---|---|
| 1. main commit | `89d1791ebdf1633e57cda5150ea43ff47921313a`; work remains local on main, no push or commit performed |
| 2. Unity | 6000.5.5f1 (`d16e074b49fd`), installed at `C:/Users/tiger/UnityEditors/6000.5.5f1`; URP remains 17.5.0 as in the received lockfile |
| 3. Compile | Existing C# compiled unchanged after repairing the Editor install; final demo compile has no CS errors |
| 4. Windows build | Baseline `artifacts/windows/baseline/FlyBaseline.exe` and Development demo `artifacts/windows/demo/FlyAscent.exe` built successfully; Windows x86_64, Mono |
| 5. Replay | 110/110 unique sequences, 0 skipped, 0 mismatches in motor or recorded neural values; STOP 60 and each other Action 10 |
| 6. Normalization | New wire-layout fixture and standard-library converter; 6 unit tests passed; original fixture unmodified |
| 7. HUD | REPLAY label, Action, sequence, N/A request IDs, raw neural rates, motor, local playback age, E2E N/A and actual adhesion counters visually checked |
| 8. Visual | Original Blender body, FBX, local provenance, URP materials, eyes, antennae, abdomen, transparent wings/veins and bristles; four Unity views checked |
| 9. Mapper | 18 major physical joints, thorax and six visual-only hip bridges; no per-frame hierarchy searches or writes to physics; maximum endpoint error approximately `6.56e-7` Unity units |
| 10. Stage | Floor, books, cup proxy, can, key obstacles and narrow ledge blockout; traversability and a balanced vertical route are not certified |
| 11. Grip | Measured attachment count/utilization/detach values displayed; all were 0 in the sampled baseline Replay; no adhesion tuning or fabricated load estimate |
| 12. Shiu Live | Python 3.10.12 / Brian2 2.5.1 / Cython 0.29.37 environment and imports ready; minimal Cython fails on missing `io.h`; no whole-brain run |
| 13. Mac comparison | Source, calibration and original recording hashes match M0; current Mac resolved package inventory and matched physical trials were not supplied; no claim of trajectory or Brain latency parity |
| 14. Blockers/limits | SDK/UCRT and v783 CSV/parquet plus manifest for Live; some idle FootPads remain above the ground in the preserved baseline pose; FORWARD_L does not produce a clean negative yaw delta in the sequential trial; stage climbing/falling balance incomplete |
| 15. Files | `changed-files.txt` lists the complete local change set; `README_WINDOWS.md` gives build/run commands |

## Compile/install diagnosis

The first automatic install used a deep workspace path. Required URP filenames
exceeded 260 characters (one missing `.cs` path was 275 characters). The install
reported success but omitted long files, leading to missing migration API and
MaterialReferenceChanger compilation errors. The first failed log is preserved as
`artifacts/windows/baseline-build.log`.

Reinstalling the **same** Editor into the shorter user directory restored those
files. The incomplete project package cache was moved to
`artifacts/windows/package-cache-longpath`, then regenerated from the repaired
Editor. `baseline-build-repaired.log` ends with exit code 0. No Unity upgrade,
package-source patch or renderer replacement was used. The default Editor install
directory was restored to `C:/Program Files/Unity/Hub/Editor`; the task-created
6000.5.5f1 registration now points to the repaired short path.

The only dependency additions for the demo are the built-in screen-capture module
and its image-conversion dependency. Initial non-visible Player capture failed;
the final four views were captured from visible Players and succeeded.

## Runtime evidence

Machine: Intel Core i7-13620H (10 cores / 16 logical processors), approximately
31.7 GiB RAM, NVIDIA RTX 4070 Laptop GPU. Source hardware JSON is in
`artifacts/windows/hardware.json`.

Final full replay: `artifacts/windows/runs/final-perspective`.

- 30-second Player run, process exit 0; 110 recorded frames observed.
- Frame-time p95: **16.69 ms**, a Player rendering measurement, not Brain step time.
- Fixed timestep: approximately 0.02 s, unchanged.
- 18 physical articulation joints + thorax, 6 FootPads.
- Visual Collider/Rigidbody/ArticulationBody total: **0**.
- Original locomotion, Scene and physics-setting hashes: **52 checked, 0 changed**.
- Builder's before/after ArticulationBody, Collider and config serialization comparison passed.
- Final runtime logs contain no observed managed runtime exceptions.
- `controls/Player.log`: emergency pause displacement **0**, scene restart requested
  and completed, separate CSV files retained, no runtime exception. These controls
  were exercised programmatically through the same handlers used by the buttons.
- `Replay_FORWARD.mp4`: 81 screen captures encoded at nominal 12 fps, clearly labeled
  REPLAY; a visual demonstration, not a real-time neural performance benchmark.

Four images: `runs/final-{perspective,front,side,top}/demo.png`.
Raw per-frame CSV preserves sequence, Action, motor, DNp09/DNa02 rates, displacement,
yaw and Grip diagnostics. `final-replay-summary.json` checks observations against
the unmodified measurements in the normalized recording.

### Observed sequential motion

These deltas span each Action's first and last observed frame, with preceding
motion and initial settling still present. They are not isolated trials.

| Action | Observed frames | yaw delta (degrees) |
|---|---:|---:|
| FORWARD | 10 | +6.779 |
| TURN_R | 10 | +10.186 |
| TURN_L | 10 | -3.610 |
| FORWARD_R | 10 | +16.089 |
| FORWARD_L | 10 | +4.131 |

FORWARD increased world z by 0.390 Unity units within its observed interval.
The six STOP blocks are separated by other actions, so their combined displacement
is not a STOP-only movement metric. Correct negative motor.turn values were retained
for FORWARD_L, but its sequential physical yaw is not a successful left-curve claim.
No CPG, joint, friction, adhesion or decoder retuning was performed to hide that.

### Renderer comparison

Visible and renderer-OFF runs used identical recorded motor sequences and both
observed all 110 frames with 18 joints/6 FootPads/zero visual physics components.
The independent runs ended 0.311 Unity units and 5.5 degrees apart. This wall-clock
Replay comparison is not a deterministic physics equality test; trajectories are
not claimed identical. `renderer-comparison.json` records the values explicitly.
One additional visible/visible repeat also differed by 0.502 Unity units and
0.976 degrees, while retaining 110/110 frames and identical motor values. This
demonstrates run-to-run variability exists; one repeat does not establish a
statistical tolerance or prove renderer-independent trajectory equivalence.

## Provenance and reproducibility

- Original recording SHA-256:
  `01bb9e218dc62311bf4e91df3fd68a59b6a000fa8a89abd30aa5f4f09e87288a`.
- Normalized recording SHA-256:
  `441f6df2556d7b887b73e9a5bd1e848acdd2ef40b4eda2e5f1b36e07be6dda1a`.
- Calibration SHA-256:
  `d9ce02e1a853188649dcd96116c7aecf16275b298957271f0d7ae2cc21257e27`.
- Visual is original local Blender work, no external mesh, texture, paid API or upload.
  `ArtSource/Blender/README.md` and `SHA256.json` describe the Blender source/export.
- Brain p95 step, E2E, RSS and whole-brain N/E are **not measured on Windows**.
  Mac's reported ~358 ms is not reused as a Windows result.
- Live TCP mode uses the existing client and is explicit opt-in. Real-server stale,
  reconnect and neural six-action checks remain unperformed pending SDK/data.

Reproduction commands are in `README_WINDOWS.md`; compiler and data details are in
`SHIU_WINDOWS.md`. Generated build/log/image/video outputs remain in ignored
`artifacts/windows`, not in the shared source or neural dataset folders.
