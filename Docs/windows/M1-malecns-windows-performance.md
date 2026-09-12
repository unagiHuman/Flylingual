# Windows MaleCNS latency diagnosis

## Findings

Read-only runtime diagnosis, Windows native CPython 3.10.12 / NumPy 1.24.3, seed 20270101, 50ms window, dt=0.1ms. Graph/config/model/decoder unchanged. No TCP or Unity in direct test.

- Direct controller: 14 windows (2 per STOP/FORWARD/TURN_R/TURN_L/FORWARD_R/FORWARD_L/STOP), mean wall 1999.70ms, process CPU 1970.98ms. This is a timing probe, not settled six-action acceptance.
- Previous TCP run mean step 2026.31ms. Removing TCP does not resolve the slowdown.
- Stored Mac 50ms benchmark mean 398.24ms; direct Windows approximately 5.02x. Mac was not rerun simultaneously and hardware/environment parity remains unverified.
- One additional profiled final STOP window: 1.980s total, shiu_compatible.py step self time 1.787s (90.3%), cumulative 1.810s; controller self time .169s (8.5%). Function-level profiling does not isolate individual NumPy expressions. This STOP sample does not characterize active synaptic propagation cost.
- The controller calls sim.step(1) 500 times per output window. Each tick updates full neuron state arrays with boolean indexed reads/writes, creates temporary arrays/count vectors, and accumulates counts. This CPU array-update path is the confirmed hotspot. Sparse synapse propagation may contribute more during active stimuli; not isolated here.
- CPU time nearly equals wall time: a roughly single-core compute workload, not mainly socket wait. GPU is not used by this implementation. No matrix BLAS hotspot was observed; changing OpenBLAS thread count is not an evidenced fix.

## Environment and affinity check

AC connected, battery 97%, Balanced scheme, processor maximum 100% AC/DC. All 16 logical CPUs available to process; 10 physical cores reported. No Unity/Player process observed during the process inventory. Other Python processes existed; their detailed CPU contribution was not measured.

Three fixed initial STOP windows per condition, same seed and fresh controller:
- Logical CPU 0: 2027 / 2050 / 1938ms.
- Logical CPU 15: 2987 / 3149 / 3046ms.
- Original all-CPU affinity: 2005 / 1978 / 1956ms.

Pinning CPU 0 did not improve the default result; CPU 15 was slower. P/E labels were not verified. The test only changed its own process affinity and restored it. No machine power setting changed. psutil reported 1520MHz current / 2400MHz maximum, but this is not a reliable per-core turbo/throttling measurement; it cannot establish thermal or power throttling.

## Conclusion and next step

Confirmed: slowdown is in CPU neuron-state calculation and persists without transport. Not established: why this CPU/Windows/NumPy combination is five times slower than the stored Mac measurement. Do not label Windows itself, power mode, or RAM bandwidth as a proven sole cause.

Next minimal investigation: line-level timing of state update/indexed-array operations and a numerically equivalent buffer-reuse prototype outside the production model. Require fixed-input neuron-state and BrainFrame equivalence before adopting any optimization. Keep dt, weights, seed, stimulation, decoder and physics unchanged. Increasing Unity stale timeout would not fix this compute bottleneck.

Evidence: artifacts/windows-malecns/profile/direct.json, step.prof, profile.txt, affinity.json. Reproducible direct profiler: tools/profile_malecns_windows.py. Small affinity sample is diagnostic, not a performance guarantee.
