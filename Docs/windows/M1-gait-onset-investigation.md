# Gait onset/contact investigation

## Evidence examined

Reanalyzed all 24 baseline/bounded-amplitude trials from coxa-check with tools/analyze_gait_onset.py. Tables are in M1-gait-onset-results.json. The illustrative numbers below are repetition 0, not a statistical mean.

FORWARD_L phase0 vs phase90: first LF Coxa target -1.03 vs -5.07deg; Femur .93 vs 4.57deg; RF Coxa +1.50 vs +7.35deg. Both conditions start with the same tripod stance labels (LM/RF/RH stance), but RF first recorded ground is .12 vs 1.22s, RH .22 vs .58s. Physical yaw exceeds 1deg at .28/.30s. Initial .25s has 64/44 non-FootPad contact callbacks respectively. First recorded actual joint state is post-solver, not a measurement of the exact instant before reset. These correlations do not establish individual foot causation or full friction impulse closure.

Controller code advances phase at full gaitFrequencyHz whenever activity exceeds threshold, while currentMotor is still ramping via motorSmoothingSeconds. The amplitude and differential scale therefore evolve while contact/stance transitions are already progressing. Phase0 and phase90 do not begin from equivalent joint targets despite the same reset pose. This explains why phase is a meaningful test variable, not proof of a specific complete causal force model.

## Additional single-variable experiment

12 fixed Replay trials, same initial state, commands, amplitudes and phase matrix; runtime-only cloned motorSmoothingSeconds=.35 instead of .12. No saved preset or production locomotion modifications. New -diagnosticMotorSmoothing option, only active under physics diagnostics. Build succeeded; 12 trials completed.

Mean yaw at 2 seconds (positive right):
- FL phase0: baseline -52.90deg -> slow ramp +49.41deg (wrong, 3/3).
- FL phase90: baseline +53.98deg -> slow ramp -28.03deg (improved by 2s, but initially right at .5/1s).
- FR phase0: +39.07deg; FR phase90: +38.80deg.

This is not a fix: increasing smoothing transfers the wrong-direction behavior to another starting phase. Reject for production. It also delays command response. Combined with the earlier zero-clamp test, neither amplitude limiting nor simple smoothing is sufficient.

## Conclusion

CONTACT_PHASE_DEPENDENCE is reinforced by a controlled change of temporal ramp: the same fixed neural output and rig can reverse physical direction when only startup timing changes. Existing joint target shaping is not robust to the contact state during startup. Brain/decoder/TCP remain excluded as the source of this fixed-Replay sign reversal.

Production physics remains unchanged; FORWARD_L remains unresolved. A robust candidate must account for stance/contact and target continuity through transition, and pass multiple initial phases and both turn signs. Do not choose a convenient initial phase, add requestedAction compensation, or mask the symptom with direct body yaw. Next design should explicitly separate steering shape from activation envelope and validate its transitions; this experiment alone does not justify adopting such a redesign.

Evidence: artifacts/windows-malecns/onset-smoothing/{summary.json,legs.csv,body.csv,contacts.csv,reset.jsonl,Player.log}; M1-onset-smoothing-results.json; onset-build.log. Diagnostic scripts: tools/analyze_gait_onset.py and tools/run_onset_diagnostic.py. No Brain/preset change in this task; no push; ready=false.
