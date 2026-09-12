# STOP timer fix and Coxa-bound experiment

## Implemented and verified

LiveIntegrationTrial initial STOP now requires an acknowledged STOP frame before counting continuous fresh/zero output, using realtimeSinceStartup difference rather than startup unscaledDeltaTime. No SerializeField, gameplay preset, neural or physical production parameter changed. Unity build passed.

Actual Windows production Brain -> localhost -> Unity basic trial completed. STOP requested t=2.62945; corresponding acknowledgment ~907ms later; INITIAL_STOP_PASS t=6.55329 (3.924s after send), consistent with at least 3 seconds after acknowledgment. FORWARD moved .40994 units along initial forward direction. Subsequent STOP motor near-zero after 2.878s; physical stable-pose confirmation after 11.499s. 45 frames, sequence increasing, metadata mismatch/error 0; stale 0/382 samples, max age .68287s. BASIC_GATE_PASS and TRIAL_COMPLETE, process exit 0. This proves one basic trial, not six-action or gameplay acceptance.

## Fixed Replay experiment (not adopted)

24 trials: baseline vs runtime-only cloned config with coxaStrideAmplitudeDegrees=35.135 (baseline 38), each FORWARD_L/R x phase 0/90 x 3. Shared previous controlled-initial.json, unchanged fixed BrainFrames, eight simulation seconds per trial. No live brain. Diagnostic -diagnosticBatch steering and -diagnosticCoxaAmplitude added; serialized assets unchanged.

Mean yaw at 2s / 8s (positive right):
- FL phase0 baseline -52.90/-125.60; bounded -43.67/-171.99.
- FL phase90 baseline +53.98/+207.45; bounded +48.19/-123.69.
- FR phase0 baseline +48.32/+261.24; bounded +42.46/+206.42.
- FR phase90 baseline +32.98/+194.02; bounded +39.00/+106.72.

No falls in these 24 trials. Recorded joint clamps fell from 3492 per-leg samples to zero. Nonetheless phase90 FL still turned right in all three trials at 2s (43.84–51.49deg). Late yaw became left in all three, but a delayed correction is not a successful direction fix. Bounded phase0 FL also had one wrong-sign final yaw. Therefore amplitude reduction alone is rejected for production.

Confirmed: eliminating saturation does not eliminate initial contact/phase-dependent reversal. Previous CONTACT_PHASE_DEPENDENCE finding stands; saturation contributes to later behavior but is not sufficient explanation for the onset. No claim of full per-contact yaw force closure.

## Remaining work

FORWARD_L physics fix remains unresolved. Next diagnosis should inspect initial stance/contact and target continuity when gait starts or changes, and test any action-independent transition change against the phase matrix. Do not fix by requestedAction correction, direct yaw torque, decoder edits, or selecting a favorable phase only. ready=false retained. No push.

Evidence: artifacts/windows-malecns/coxa-check/{baseline,bounded}/; Docs/windows/M1-coxa-bound-comparison.json; artifacts/windows-malecns/unity-stop-timer-fixed/; artifacts/windows-malecns/steering-build.log. Initial state reference: ../Flytest/artifacts/windows/physics-diagnostic/controlled-initial.json. Existing finite test runner updated to basic trial with benchmark mode enabled, avoiding Title pause.
