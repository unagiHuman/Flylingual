# M5-M7 exploratory MaleCNS dynamics report

Captured 2026-09-11 JST. These results use the explicitly approved exploratory NT policy and do not establish biological validity.

## M5 runtime

- Runtime representation: 211,577 neurons and 19,848,648 effective edges in presynaptic CSR.
- API: `initialize()`, `set_stimulation(...)`, `step(...)`, and `get_readout()`.
- Dynamics: persistent NumPy implementation using the Shiu-style resting/reset/threshold, membrane/synapse time constants, refractory duration, delay, and base weight.
- The first same-coefficient run (`recurrentWeightScale=1.0`) became persistently overactive after stimulation and failed acceptance.
- Explicit tuning runs at 0.01, 0.05, 0.10, and 0.20 were kept separate. Scale 0.10 avoided runaway activity while producing the required candidate responses with top-10 direct input groups.

## M6 causal path and motor readout

The minimum causal PoC path is:

`AN03A008_R body 13137 -> DNa02_R body 10360`, with structural weight 717.

Across seeds 20260911, 20260912, and 20260913 at 100 Hz for 50 ms:

- baseline DNa02_R: 0/0/0 Hz;
- stimulated DNa02_R: 60/60/80 Hz;
- same stimulus with the direct edge blocked: 0/0/0 Hz.

Stimulus and readout ID sets are disjoint. This verifies a saved MaleCNS connection-dependent response for the PoC, not walking behavior or biological causality.

Two training seeds produced a PoC calibration of forward reference 20 Hz, turn reference 93 Hz, and turn deadzone 5 Hz. The holdout seed produced motor outputs F=1.0, R=+0.85, L=-0.85, F+R=(1.0,+0.63), and F+L=(1.0,-1.0). The decoder reads raw rates only and does not read the Action name.

## M7 persistence and performance

The three seeds ran `STOP -> F -> STOP -> R -> STOP -> L -> STOP -> F+R -> STOP -> F+L -> STOP` with one network construction and zero state resets. Normal STOP disables external stimulation but does not erase residual activity.

For 50 ms windows at scale 0.10, mean step time was about 657-660 ms and p95 was about 728-765 ms, giving a wall/sim ratio of about 13.1-13.2. The provisional 250 ms p95 target is not met. E2E with a TCP client and Unity was not measured.

## Status

- M5 minimal dynamics: implemented and smoke-tested.
- M6 minimum saved-edge response and raw-to-motor PoC: passed with limitations above.
- M7 persistence: passed; performance target failed.
- Live server/port 8766 and Windows Live integration: not yet implemented or tested.
