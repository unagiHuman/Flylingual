# Contact-aware gait implementation: first increment

Implemented structural groundwork; contact-based gait changes are NOT enabled yet. FORWARD_L remains unresolved.

- FlyLeg.CalculateNominalTargets computes target angles, base angles, stance and stance progress without joint/adhesion writes.
- FlyLeg.ApplyDriveTargets is the single application point, preserving SetStance before joint writes and Coxa/Femur/Tibia application order.
- ApplyTrajectory remains a compatibility entry point delegating to those two methods. Existing serialized fields and callers remain valid.
- FlyFootContact now exposes remaining hold ticks, last contact fixed time and DIRECT_COLLISION/ARTICULATION_OWNER provenance. These are observational properties only. Existing 3-tick hold and AdvanceAdhesionTick owner are unchanged. Snapshot ordering and true contact-point velocity are not implemented by this increment.
- GaitTargetRegression.RunAndBuild compares pure calculations to pre-refactor recorded targets and stances, then builds only on success. It requires artifacts/windows-malecns/coxa-check/baseline/legs.csv; missing evidence causes a failure rather than a skipped test. Unity generated the new script meta.

Validation: 28,800 recorded leg samples; maximum angle error 0; all stance values matched. These cover the existing FL/FR phase0/90 baseline trials, not arbitrary reflex offsets or all possible inputs. The comparison does not claim every physical trajectory is bit-identical. Unity 6000.5.5f1 Windows Player build succeeded, exit 0. No new physical gameplay acceptance run in this increment.

No contact-aware coordinator/Hermite transition has been connected yet; no new per-leg activation policy or target adjustment was introduced. Existing diagnostic separate-steering remains default OFF. No Brain/decoder/preset changes in this increment. SerializeField changes: none. ready=false. No push.

Evidence: artifacts/windows-malecns/gait-target-regression.json and gait-refactor-build.log. Next increment: coherent read-only observation snapshot, then diagnostic-only trajectory transition; maintain the recorded baseline gate before introducing contact scheduling.
