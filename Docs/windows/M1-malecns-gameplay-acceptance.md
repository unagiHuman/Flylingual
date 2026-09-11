# MaleCNS gameplay acceptance

Status: NOT RUN / NOT READY. No 5–10 minute Live play session has occurred.

Latest classification: MaleCNS/TCP integration_ready=true, Gameplay/Physics gate remains
unpassed. The fixed-Replay diagnosis is in `physics-diagnostic/README.md`.
Earlier integration_ready=false wording below describes the prior gate classification.

Update: Unity Live transport and STOP→FORWARD→STOP were subsequently tested.
Six-action physical gate failed: FORWARD_L motor/CPG turn were negative but body
yaw moved +18.10 degrees in the scene. Therefore the longer gameplay acceptance
session was not started. STOP pose recovery windows ranged about 2.02–7.90 seconds
in single trials; FR stop net displacement was .58 Unity units. See the Live report
for thresholds, transient/terrain caveats and exact logs. Communication was healthy
(200 frames, zero protocol errors/stale samples); this is a gameplay/physical-control
blocker rather than a TCP failure. ready=false and integration_ready=false remain.

simulation_ready=true is the Mac handoff result. Windows parser and HUD pass;
Replay integration remains provisional. integration_ready=false,
gameplay_ready=false, ready=false. No server status was modified.

Observed Replay risks: FORWARD motor.turn=0 still produced approximately +43.34
degrees yaw over ten simulated seconds; left/right turning magnitudes differ.
STOP recovery clips contain real residual outputs, so concatenating all STOP
segments is not a valid persistent STOP test or a substitute for Live response.

Pending measurements: five moving-action onset distributions, FORWARD/FR/FL→STOP
recovery time and distance, grip effect and fall counts, cliff stopping, reversal,
reconnect/stale, and concrete 5–10 minute gameplay examples. All remain unavailable,
not zero. Offline rendering p95 is not brain or input response latency.

Keep the accepted Shiu Replay demo as the working gameplay baseline. Do not change
EMA, hysteresis, LIF, populations or MotorDecoder on Windows to hide these risks.
Mac endpoint is still required after the Replay gate is resolved. Share the actual
measurements with Mac before any ready=true decision.
