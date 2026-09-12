# Direct spike-count accumulation: production and Unity validation

Production change: optional count_buffer in LIF.step; omitted argument preserves freshly allocated return counts. Controller passes its window-owned accumulator directly instead of allocating and adding a full count vector every tick. No dt, constants, weights, neural input, decoder, CPG, physics, Unity source or stale threshold change. Updated manifest hashes preserve original baseline hashes.

Reprofile after float-buffer optimization: .635s profiled STOP window; controller self .158s. Count accumulation candidate reduced paired mean .64674s to .46072s. Three seeds 20270101–03, 7 action segments x 8 windows x 3 = 168 windows. Every BrainFrame excluding timing, v/g/last/rfc arrays, pending spikes and RNG state matched exactly. This is bounded window-level equivalence; not an exhaustive state-space or record=True test. Reference and candidate ran serially, reference first; timing ordering bias is possible. Diagnostic code normalizes back to the pre-count implementation so it remains rerunnable after adoption.

## Actual Unity production test

Existing previously successful Unity build reused (no Unity edits). Real production Windows server, 127.0.0.1:18766, single Unity client, -demoAction ALL -demoLive -liveTrial -liveSix. Server and Player exited after the test. No Mac, mock, synthetic motor or automatic fallback.

136 frames, increasing sequence, metadata mismatches 0, protocol errors 0. Observed stale samples 0/1302, maximum sampled frame age .70257s. Mean server step .58010s, p95 .65762s, max .70474s. These results are one roughly 79-second test, not a sustained load guarantee.

Actual FORWARD projection .69305 units. Moving-action correlated response .629–1.129s. Motor returned near zero after STOP in 2.31–3.66s. Physical stable pose was confirmed after the first four movement segments in 4.80–6.31s.

Direction observations (signed accumulated yaw across each 8s segment): FORWARD +38.40deg; TURN_R +54.65; TURN_L -83.23; FORWARD_R +29.04; FORWARD_L +33.30 (opposite requested turn). Initial FORWARD includes settling, so its onset proxy is not a valid controlled latency measurement. This live sequence did not reset body pose between actions; sign behavior is not isolated causal physics diagnosis.

Final FORWARD_L was followed by falling. Final STOP motor returned to zero but body continued falling, so physical_stop_timeout fired after 15s. The benchmark disables the normal game session/restart handling. Thus the final result is not gameplay acceptance and not a neural STOP failure. Final screenshot inspected; trajectory records large negative y displacement. No managed exception observed; the Player log retains an existing d3d12 info-queue warning.

## Important test limitation

Existing LiveIntegrationTrial accumulates Time.unscaledDeltaTime during startup; INITIAL_STOP_PASS occurred only .50 wall seconds after STOP, not 3 seconds, and the initial request lacked a correlated acknowledgment before FORWARD. Do not claim the strict initial STOP gate passed. Real subsequent frames, movement and STOP recovery are measured; the diagnostic startup timer needs a separate small correction before claiming full formal gate acceptance.

Conclusion: CPU bottleneck reduced enough for no sampled stale in this run; production receives and drives the physical fly. Gameplay remains blocked by the existing FORWARD_L direction problem and fall behavior. ready=false remains. No commit/push.

Evidence: artifacts/windows-malecns/count-buffer/results.json; unity-production-count/{live-wire.jsonl,live-motion.csv,live-events.txt,analysis.json,Player.log,live-result.png,process-result.json}. Compact results and hashes: M1-malecns-count-buffer-results.json. Production reprofile overwrote profile/direct.json and profile.txt; previous profiling conclusions remain in their dated reports.
