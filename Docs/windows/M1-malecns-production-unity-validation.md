# Production buffer optimization and Windows Unity validation

## Implemented

Brain/MaleCNS/shiu_compatible.py: two reusable float64 arrays; replace the two boolean-indexed state updates with ordered ufunc out operations and active-mask copy/update. No neural constants, model, decoder, input, timestep, physics or stale threshold changes.

analog_handoff_manifest.json: update the changed source hash and retain the previous hash under priorRepoFileHashes. All four graph hashes and current listed repository hashes passed verify_analog_assets.py. Regression against the previously validated candidate passed 14 exact state/BrainFrame windows (excluding performance timing). Earlier 3 seeds / 148 windows established candidate-to-original sampled equivalence.

Diagnostic tools now load the pinned original from commit 5d741284f9633c8667c258184893b3aafaa5b5a2 via tools/malecns_reference.py, so the original baseline remains available after production adoption.

## Build

Unity 6000.5.5f1 BuildMaleCnsIntegration succeeded, exit 0. Player: artifacts/windows/m1/player/FlyAscent.exe. C# compile errors not observed. Initial sandbox license failure resolved by using existing licensed user context. No Unity source, scene, serialized fields or preset modified.

## Actual Windows-only Unity trial

Production server at 127.0.0.1:18766, no candidate injection, Mac or mock client. First launch omitted -demoAction ALL; Title paused physics. This run is preserved separately and is not a physical validation. Its failure screenshot led to correcting the CLI invocation using the existing benchmark option, without changing Unity code.

Corrected run: -demoAction ALL -demoLive -liveTrial -liveSix. Physics active; actual fly settled onto the surface. Screenshot inspected.

- Received 25 BrainFrames; sequence progressed; metadata mismatches 0; protocol errors 0; no managed exception observed.
- Backend MALECNS_EXPERIMENTAL, ready=false; all sampled motor outputs exactly zero during STOP.
- STOP request corresponding frame: 1174.52ms.
- Server step mean 798.27ms, p95 912.62ms with Unity running.
- 22/325 sampled motion records exceeded .75s frame age (sample count, not distinct stale episodes); maximum age .931186s.
- Initial STOP gate FAILED at 20s: freshness could not remain <.75s for 3 continuous seconds. Physical pose stabilized, but freshness gate did not pass.
- FORWARD, STOP-after-FORWARD, remaining movement actions: NOT_RUN because initial gate failed. Existing FORWARD_L physics issue remains unresolved.
- Corrected Player exited 0 after logging FAIL; this process code is not a test pass. Harness stopped its own brain process. First paused-title Player required explicit termination because Invoke-based quit did not advance while paused; preserved as a harness limitation.

## Conclusion

Production optimization applied and compiled Windows Player receiving real Windows-native brain frames verified. Windows-only Unity movement acceptance remains FAILED/BLOCKED by freshness cadence. ready=false maintained. Do not increase stale timeout or claim gameplay acceptance based on successful transport. No commit/push performed in this task.

Evidence: artifacts/windows-malecns/production-equivalence.json; unity-build.log; unity-production/ (first attempt); unity-production-physics/ (corrected run: live-wire.jsonl, live-motion.csv, live-events.txt, analysis.json, Player.log, live-result.png, process-result.json).
