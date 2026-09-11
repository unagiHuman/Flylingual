# MaleCNS Windows → Mac Live validation

Status: MaleCNS/TCP integration PASS (integration_ready=true); Gameplay/Physics gate FAIL (FORWARD_L). ready=false retained.

Latest gate classification follows the user's acceptance of the successful MaleCNS→TCP→Unity path.
Physical diagnosis is now recorded in `physics-diagnostic/README.md`; a physics failure
does not retract transport integration success. Earlier gate terminology below is historical.

## Unity Live actual results — 2026-09-11

Tested Unity Standalone Player, Unity 6000.5.5f1; not an Editor Play-mode test.
Source remains detached at 253a1ec plus the local integration changes listed below.
Only Unity connected during these tests, no mock/probe overlap. Both Players closed
their sockets and exited. Two successive Unity connections succeeded after the mock,
without controller_already_connected; this supplies practical slot-release evidence.

Evidence:
- `artifacts/windows/m1/live/unity-basic-20260911-161632/`
- `artifacts/windows/m1/live/unity-six-20260911-161958/`
- Build logs `artifacts/windows/m1-live-build.log`, `m1-live-pose-build.log`.

The six-action run received 200 BrainFrames with increasing sequence, zero metadata
mismatches, zero protocol errors, zero managed Player exceptions and zero stale
samples. Maximum observed frame age .38 seconds against unchanged .75-second timeout.
HUD screenshots show MALECNS EXPERIMENTAL / CONNECTED / ready=false.
The stimulus driver calls BrainTcpClient.SetAction, sends real TCP commands, and
consumes Mac frames through BrainMotorSource and the unchanged locomotion/CPG/PhysX.
It never writes root pose, force, motor values or decoder parameters.

| Input (8-second observation) | Request→corresponding frame ms | Body yaw change | Pose onset proxy s |
|---|---:|---:|---:|
| FORWARD | 519.59 | +58.71 degrees | excluded: initial settling overlap |
| TURN_R | 500.41 | +56.29 degrees | 1.68 |
| TURN_L | 767.25 | -21.09 degrees | 1.40 |
| FORWARD_R | 437.34 | +221.66 degrees | .97 |
| FORWARD_L | 698.59 | **+18.10 degrees (wrong direction)** | 1.06 |

FORWARD advanced 1.426 units projected onto its initial forward direction in the
second run (first run .619). Forward has substantial yaw bias. Actions were tested
sequentially with STOP between them, not from identical poses or terrain contacts.
FORWARD_L began near the notebook ramp, which is a possible contact-dependent factor.
No claim of a flat-ground causal reproduction or a neural-model fault is made.
Nevertheless the actual game-body direction did not match the requested left turn.

FORWARD_L observed mean motor.turn=-.6684, mean CPG turn=-.6576; final values
-.81589 / -.83199. Body yaw 40.508→58.609 degrees despite those negative signals.
The problem is downstream of the received motor sign in this scene; a contact/rig
diagnostic is required before asserting a specific mechanism. No action compensation
was added. The correct source signs are not a six-action physical acceptance pass.

## STOP response and visual observation

| After | Frame motor near-zero s | Start of observed stable-pose window s | Net stop displacement (Unity units) |
|---|---:|---:|---:|
| FORWARD | 2.60 | 3.20 | .47 |
| TURN_R | 1.89 | 7.90 | .04 |
| TURN_L | 1.70 | 2.02 | .14 |
| FORWARD_R | 2.60 | 6.45 | .58 |
| FORWARD_L | 2.46 | 3.06 | .24 |

Near-zero is abs(forward/turn)≤.01. Pose window is ≥1 second with position within
.01 units and yaw within 1 degree. Confirmation necessarily occurs after the window.
These are single observations, not percentiles or population estimates. Onset proxy
is >.02 units displacement or >.5-degree yaw for pure turns at roughly 20 Hz sampling.
It is not a human perceptual latency measurement. One-second screenshot captures
were inspected for forward movement, stationary STOP pose and the left-turn trial;
their temporal resolution cannot substantiate subsecond visual onset precision.

The first run's solver-velocity criterion (.03 units/s and 2 degrees/s continuously)
timed out after 15 seconds despite stationary screenshots. Contact solver velocity
oscillated while actual root position stayed almost fixed. That failure is retained;
only the observer was changed to the pose-envelope criterion, no physics adjustment.
The subsequent run confirmed basic STOP→FORWARD→STOP and then all four turning inputs.
`TRIAL_COMPLETE` means data collection finished, not that every physical sign passed.

## Gate and changes

Transport / frame reception: PASS. Basic forward/stop: PASS with yaw bias and delay.
Six-action physical direction: FAIL. integration_ready=false, gameplay_ready=false,
ready=false. The 5–10-minute gameplay acceptance session was not started because the
required direction gate failed. No success is inferred from TCP alone.

Local changes for Live: BrainTcpClient runtime endpoint setter, opt-out reconnect,
optional forced STOP send, raw send/receive observer events, preserved server error
code; WindowsReplayDemo CLI endpoint and Live identity; LiveIntegrationTrial runtime
observer/stimulus component; tools/analyze_unity_live.py. No SerializeField changes,
scene/preset/physics/MaleCNS model/decoder changes, main merge or push.
Normal game W/A/D routing remains Replay-oriented; this was an instrumented Player
trial with actual physics, not a manual 5–10-minute game session.

The following sections retain the earlier mock history and prerequisites.

## First controller session after Mac clean restart

2026-09-11 15:52:37–15:53:00 JST, host 192.168.1.7:8766, Mac PID reported 47453.
One TCP connection only, no preceding probe or retry. Client process completed and
closed the socket normally. Server-side controller release is not yet confirmed;
Mac must verify it before another client or Unity connects.

Log: `artifacts/windows/m1/live/mock-client-validation-20260911-first.json`.
Probe: `tools/probe_malecns_live.py`, based on existing mock NDJSON commands,
with 15-second receive timeout, immediate error handling, incremental full-response
logging and finally-block disconnect. No MaleCNS code/model/decoder changes.

TCP connected, status received, first BrainFrame arrived 23.48 ms after connect.
That initial streaming frame predates the new STOP acknowledgement and is not
the STOP action-response latency. First request-correlated STOP frame: 390.21 ms.

| Action | First request-correlated frame ms | Sequence range | Last motor forward / turn |
|---|---:|---|---|
| STOP | 390.21 | 2067–2074 | 0 / 0 |
| FORWARD | 736.14 | 2076–2083 | positive / 0 |
| TURN_R | 733.70 | 2085–2092 | 0 / positive |
| TURN_L | 748.18 | 2094–2101 | 0 / negative |
| FORWARD_R | 728.88 | 2103–2110 | positive / positive |
| FORWARD_L | 695.10 | 2112–2119 | positive / negative |
| STOP | 704.17 | 2121–2128 | 0 / 0 |

Eight matching frames per request, sequence strictly increases, all six Action
types reach expected signs. Backend MALECNS_EXPERIMENTAL, ready=false throughout;
protocol errors zero, controller_already_connected absent.

Final STOP reaches exact motor zero at sequence 2126, 2539.14 ms after sending,
and remains zero for the last three observed frames (through 3275.58 ms).
The probe's stricter last-four-frame stability criterion returns false/exit 1:
sequence 2125 still has forward ~.03. This is preserved in the log, not treated as
a transport failure or evidence of failure to stop. Four consecutive zero frames
were not observed in this finite eight-frame window. This is motor response,
not visible-motion stop latency, stopping distance or gameplay acceptance.

No reconnect was attempted. Client-side close succeeded; Mac-side release and
acceptance of the next client remain pending. Unity was not started or connected.

## Previous prerequisites and remaining Unity work

Source 253a1ec9eda78a14873999325bbe7d697918f715; Unity 6000.5.5f1.
Replay gameplay acceptance remains provisional. The Mac LAN endpoint was subsequently
provided and TCP reachability passed once before the clean restart. No network
scanning or firewall modification was done.

Pending: server-side release confirmation, disconnect/reconnect, Unity Live 6
actions ×5, Latest Action Wins, stale safe-stop,
disconnect/reconnect, actual input-to-visible-motion and STOP recovery measurements.
The table above measures request-to-frame latency only; Windows visible onset/release
numbers remain unavailable. Mac localhost p95 ~799ms is handoff evidence only.

Current game controls are Replay-oriented: Begin selects Replay and W/A/D dispatch
is gated to Replay. BrainTcpClient host/port are serialized and no runtime endpoint
setter exists. Live gameplay needs a small routing/endpoint integration after the
Replay gate, preserving latest-action and stale behavior. This was not silently
treated as already complete. Server model/config/status were not changed.
