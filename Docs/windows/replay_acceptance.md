# Windows Replay acceptance

**PASS — Replay gameplay frozen after the final input-buffer build.**
Machine-checkable results: `replay_acceptance_results.json`.
Source/preset/build SHA256 freeze: `replay_freeze.json`.

| Final check | Result |
|---|---|
| Windows build / exceptions | 6000.5.5f1 build pass / 0 Player exceptions |
| 110-frame Replay | 110 unique observed / 0 skipped / 0 recorded-value mismatches |
| Native W/A/D / R | Correct recorded actions / title and state reset verified |
| FORWARD_L / FORWARD_R | -96.687° / +351.746° in identical 501-step, 10.000086 s windows |
| START → ramp → summit → GOAL | 3/3: 49.509 s, 44.725 s, 40.748 s |
| Physical grip | Nonzero adhesion plus real ramp/summit FootPad contacts in every run |
| Natural fall → restart | Fall at 43.511 s; measured fresh spawn and resumed game |
| Goal false positives | Head distance/height checked on every winning sample; 6 boundary checks |
| HUD / Visual | Backend, neural/motor/grip HUD and fly appearance inspected in Player |

Final evidence batches (all from the same final build):
`artifacts/windows/check-20260911-132613` (3 goals), `check-20260911-132846`
(fall/restart), `check-20260911-132938` (steering), `check-20260911-133013`
(110 frames). The native keyboard run is listed below.
Render frame time p95: 16.6843 ms; visual endpoint error max 5.9624e-7 units.
These are rendering metrics, not brain-computation or network latency.

The traversals used the documented test input driver and actual physics, not
manual play or synthetic goal triggering. This acceptance covers the short
notebook course; equal left/right speed or arbitrary tall-wall climbing is not claimed.
Further gameplay/preset changes require a new acceptance run. MaleCNS remains
unmodified and is not enabled while waiting for the Mac ready=true handoff.

Source main: `c0abf753283dc794ab09c29d0828d7fd55e4338a`.
Editor: Unity 6000.5.5f1 (`d16e074b49fd`). Source recording remains Shiu,
110 frames, SHA256 `01bb9e218dc62311bf4e91df3fd68a59b6a000fa8a89abd30aa5f4f09e87288a`.
Normalized wire fixture SHA256: `441f6df2556d7b887b73e9a5bd1e848acdd2ef40b4eda2e5f1b36e07be6dda1a`.

## Steering finding and fix

The recorded clips are not exact mirrors: mean FORWARD_L forward/turn is
0.8333 / -0.8362; FORWARD_R is 0.7667 / +0.7517. The left input is not weaker.
CPG logs confirm the sign reaches the smoothed motor and the left/right gait
scales swap in the expected direction. There is no action-label correction.

Matched new-process trials with identical starting pose and phase showed the
old gain .5 yielded -17.02° left versus +265.92° right over about 13.42 seconds.
The physical response has a strong right bias; the earlier sequential ALL test
also carried prior motion into FORWARD_L, so it was not a matched trial.
Changing only steering gain to 1.0 yielded -106.57° left and +377.02° right.
However, the full-preset trial after actual settling still produced +35.74°
for FORWARD_L. Gain alone was therefore rejected as a complete fix.

The fix shares the side-scale function between controller diagnostics and leg
targets, and allows the inside stride to reverse for strong motor.turn. The game
preset uses gain 1.5 and minimum side scale -.5. Existing scenes retain the .15
lower bound and old behavior. This is differential gait, not a decoder edit,
root torque, or action-label correction. Equal left/right angular speed is not claimed.

The first diagnostic version used wall time to request settling, and startup
consumed that interval before the first physics tick. Both sides still began at
the same 0/1.45/0 pose and phase 0. This was corrected to count physics steps for
the final full-preset checks. Original logs are retained, not re-labelled.

Per-step CSV records raw BrainFrame motor, smoothed CPG motor, left/right scales,
phase, each leg's three actual clamped targets, root pose and yaw rate, and grip
forces. `tools/analyze_steering.py` unwraps observed yaw; it never interpolates.
Earlier comparisons: `artifacts/windows/steering-baseline` and `steering-gain1`.

## Frozen gameplay preset and stage

`UnityProject/Assets/Config/FlyGameplayPreset.asset`:

| Setting | Value |
|---|---:|
| normal adhesion | .12 body-weight ratio |
| shear adhesion | .10 body-weight ratio |
| attachment delay | .02 s |
| detach threshold | 1.25 |
| gait frequency | 1.6 Hz |
| steering gain / minimum inner stride | 1.5 / -.5 |
| camera offset | (7, 7, -10) |
| camera look-ahead / FOV | 2 / 43° |

The preset applies to a runtime config copy and existing adhesion API. Of the 52
original protected files, the three authorized steering-path C# files changed:
FlyLocomotionConfig, FlyLocomotionController and FlyLeg. Joint geometry, FootPads,
friction, decoder, original scenes/settings and source config remain unchanged.
No root steering force or pose teleport was introduced.

An actual first trial stalled for 90 seconds near the keyboard. Moving it outside
the swept-leg corridor and reducing the notebook ramp to 2° resolved progression.
The route rises .08 world units to the notebook summit. The ramp and summit were
widened to desk width after signed steering exposed a side-edge stall; keyboard
props moved farther back. High props remain scenery;
this is not a claim of arbitrary vertical-wall climbing. FootPad contact on both
ramp and summit is logged, along with nonzero physical adhesion forces.

The first successful candidate reached GOAL in 61.526 s. The final build adds
a tighter goal-height gate (±.45 units) and visual-only .65° / 17 Hz wing motion.
Six boundary cases cover spawn, goal, fall, high/low false goals and radius.
The reach point is the anatomical head center, 1.04 units forward of the thorax,
matching the visual source. A thorax-only test left the fly at the sugar without
clearing when approaching from behind. The head point is used
for both goal distance and evaluation, with the same radius and tight height gate.
Both thorax and head positions are recorded in final CSV evidence.
Native input verification then exposed very short key taps being pressed/released
within one render frame. A 100 ms minimum key pulse fixes that input loss without
changing recorded motor values. W/A/D now produce measured FORWARD (.833, 0),
TURN_L (0, -.991), TURN_R (0, .819) frames; release returns to STOP. Native R returns
to the title screen. Evidence: `artifacts/windows/native-input-proof.json` and the
Player run `artifacts/windows/runs/20260911-132348-203`.

## Acceptance method

`CourseTrial` is enabled only by an explicit test argument. It chooses the same
W/A/D recorded inputs available to the player using observed heading. It never
changes BrainFrame fields, root pose, forces, stage or goal. These are automated
physical traversals, not a movie, teleport test, or synthetic goal invocation.
Each run starts a separate Player process; actual terminal game state owns success.
Normal game launch does not enable the test driver.

UI displays `Backend: REPLAY / Shiu Brain Recording`, Action, DNp09, DNa02 L/R,
Forward, Turn and per-foot grip load/attachment. Wing transparency, veins, abdomen
bands, antennae, bristles and joint-driven legs remain visible from the game camera.
Grip bars are measured load, not remaining strength; the inherited normal-force
budget can fill a bar whenever a foot is attached.

Earlier candidate evidence is stored under `artifacts/windows/acceptance`; generated files are
ignored. `tools/analyze_course.py` reports actual contact and terminal-state samples.
The gain-only candidate completed three traversals (54.733 / 48.988 / 59.440 s)
and a natural fall/restart, but was not frozen because the settled steering check
failed. Intermediate signed-steering evidence is under `artifacts/windows/signed-acceptance`.
Only the final batches listed at the top are the freeze acceptance evidence.

## Commands

```powershell
./tools/Build-WindowsDemo.ps1 -RecreateScene
./tools/Start-Replay.ps1
./tools/Start-Replay.ps1 -Action ALL -Capture -QuitAfter 30
python -m unittest discover -s tools -p test_normalize_shiu_replay.py
python tools/analyze_course.py artifacts/windows/acceptance
python tools/analyze_steering.py artifacts/windows/acceptance
./tools/Test-WindowsReplay.ps1 -Test Goal
./tools/Test-WindowsReplay.ps1 -Test Fall
./tools/Test-WindowsReplay.ps1 -Test Steering
./tools/Test-WindowsReplay.ps1 -Test Frames
```

Player test arguments: `-courseTrial goal`, `-courseTrial fall`, or
`-demoAction STOP -steeringTrial FORWARD_L -steeringGain 1.5 -signedSteering -trialAdhesion`.
Always provide a unique `-demoOutput` folder and bounded `-demoQuitAfter`.
MaleCNS and Shiu Live were not used. Changes remain local and uncommitted.
