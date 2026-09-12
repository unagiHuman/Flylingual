# Separate steering shape diagnostic — rejected

Hypothesis: smoothing turn together with forward weakens steering shape during startup, potentially causing FORWARD_L to start in the wrong direction.

Candidate: retain original smoothed currentMotor for gaitDrive and phase activity, but use targetMotor.turn for SideScale. Only -physicsDiagnostic -diagnosticSeparateSteering opts in; DiagnosticSeparateSteering is a nonserialized property defaulting false. No requestedAction lookup, body torque, phase reset or saved preset edit. FlyLeg's optional steeringTurn defaults to current motor turn; normal controller passes the same current turn as before. Not a full contact-aware target continuity solution; moving-command transition continuity is not established by this experiment.

12 trials, same fixed frames and initial state: FL/FR x phase0/90 x 3, 8s each. Updated diagnostic logs report actual candidate sideScale rather than the original formula. Build passed; all trials exited normally.

FL phase90: yaw2 = +49.46,+45.41,+51.32deg; yaw8=+215.93,+102.75,+242.08deg. Wrong direction persisted in all three. FL phase0 yaw2 negative for all three, but one wrong-sign final yaw. FR yaw2 positive for all six; one final yaw near zero/negative. These comparisons are finite seeded physical resets, not an exhaustive guarantee.

Decision: REJECTED for production activation. Reducing startup steering attenuation does not remove the reversal. Neither earlier amplitude limiting, slower motor ramp, nor this steering/envelope separation establishes a robust fix. Do not combine them blindly or claim a corrected FORWARD_L.

This narrows the diagnosis: early joint targets differ with phase and contacts, but the presence of a target discontinuity alone has not been proven to cause the sign reversal. A contact-aware transition design still needs explicit support-state and joint-trajectory reasoning, with measured impulse limitations preserved. Current per-contact observations do not close tangential impulse balance; do not invent a foot force explanation.

Modified files in this task: FlyLocomotionController.cs (diagnostic-only opt-in and TrajectoryTurn), FlyLeg.cs (optional steering shape), FixedPhysicsDiagnostic.cs (opt-in/logging), tools/run_separate_steering_diagnostic.py; reports. SerializeField/preset changes: none. Default gameplay remains original. Brain/decoder unchanged. ready=false, no push.

Evidence: artifacts/windows-malecns/separate-steering/ and separate-build.log; M1-separate-steering-results.json. Reproduce with tools/run_separate_steering_diagnostic.py after building the diagnostic Player. Original baseline: artifacts/windows-malecns/coxa-check/baseline/.
