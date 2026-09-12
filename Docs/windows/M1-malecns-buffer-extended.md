# Extended buffer candidate validation

## Scope

Diagnostic candidate only. Production Brain/MaleCNS, decoder, config, Unity, dt, weights, neural stimulus, power settings and stale threshold unchanged. Windows native NumPy 1.24.3. No Mac connection. Candidate server used localhost port 18766 and was terminated by its owning harness after clients disconnected.

## Numerical equivalence

Two additional seeds 20270102/20270103, 60 output windows each: initial STOP 4, five moving actions 8 each, final STOP 16. Same 50ms window, .1ms dt, graph/config and alternating execution order. Every one of 120 windows passed exact v/g/last/rfc array equality, pending spikes/tick/RNG state equality, and complete BrainFrame equality excluding performance timing. Final STOP decay matched and sustained zero output was observed. Including earlier seed 20270101: 3 seeds / 148 uninstrumented windows, with different sequence lengths.

Paired additional tests: original mean 2051.34ms, candidate 676.61ms (3.03x). This proves bounded sampled equivalence, not all possible states, per-tick trace equivalence, or record=True behavior.

## Actual candidate TCP test

Same existing analog server and worker classes; candidate LIF class injected only inside the diagnostic process. Seed 20270101. 15s per-read timeout. Single controller, 8 frames per moving Action, 16 per STOP. STOP observation was deliberately longer than the older eight-frame test; no production timeout change. This can change RNG timing/history versus older TCP runs, so historical latency comparisons are indicative, not exactly aligned paired simulations.

- Received 79 real BrainFrames; sequence increasing; six Action stable signs pass.
- First stream frame 449.41ms (not necessarily correlated with request).
- Correlated input response: STOP 1078.49ms; FORWARD 1274.15ms; TURN_R 1433.73ms; TURN_L 1423.44ms; FORWARD_R 1390.97ms; FORWARD_L 1377.02ms; final STOP 1382.28ms.
- Mean step 687.30ms, p95 747.82ms; 4/79 step times >750ms. These are server compute times, not measured Unity stale events.
- Final STOP first near-zero motor at 4681.62ms after request; stable last-four STOP frames passed. This is motor output, not physical body stopping.
- Protocol errors 0; backend MALECNS_EXPERIMENTAL; ready=false throughout.
- Client disconnected normally; next connection got status and continuing sequence; second client disconnected normally. No controller rejection.

## Decision

The buffer candidate is numerically consistent across tested seeds and improves actual localhost latency. It is not installed in production yet. Windows Unity gameplay acceptance is still open: p95 is close to the existing 750ms threshold and 4 samples exceeded it; STOP motor recovery remains about 4.7s. Do not raise ready or silently lengthen stale timeout based on this test. The known FORWARD_L physical reversal remains separate and unfixed.

Next implementation candidate is the already tested two-statement state-update replacement plus two allocated scratch buffers, with an explicit production diff and regression verification. This report does not authorize a model or decoder change.

## Evidence and reproduction

- tools/validate_malecns_buffers_extended.py: paired comparison; --server runs the diagnostic candidate only.
- tools/probe_malecns_candidate_tcp.py: owns server lifecycle and probes localhost.
- Docs/windows/M1-malecns-buffer-extended-results.json: compact results.
- artifacts/windows-malecns/buffer-extended/equivalence.json, tcp.json, reconnect.json, candidate-server.log: raw evidence (Git ignored).

The candidate generator is reused from tools/probe_malecns_buffers.py. Run scripts with artifacts/windows-malecns/.venv/Scripts/python.exe, without -O (assertions are validation gates).
