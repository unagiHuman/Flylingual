# Neuron-only / Shiu-compatible checkpoint

**Shiu-compatible LIF dynamics applied to the MaleCNS connectome** is an
experimental model, not official MaleCNS neural dynamics. `ready=false`.
No VNC exploration, MotorDecoder, Windows integration, Unity or optimization.

## Reproduction and selection

From Parallel using flybrain-malecns Python: `python Brain/MaleCNS/neuron_checkpoint.py`.
Requires existing structural/signed artifacts and ../Data/malecns/v1.0.
Outputs: artifacts/neuron_checkpoint. Versioned JSON snapshots: checkpoints/neuron-shiu/.
Brian2 parity failure prevents full graph execution.

Keep annotation superclass.notna() and status != Glia. All included superclass
labels are enumerated in graph_audit.json. Null superclass is excluded as
UNCLASSIFIED, not asserted non-neuronal. This is an annotation-defined population,
not a claim of biological completeness. Observed N=166700 is not forced to a target.
Both edge endpoints must survive. Sorted int64 IDs map to contiguous int32 indices.
Structural pre/post/count/sign and effective CSR are sparse; no dense NxN matrix.
ACh=+1, GABA=-1, others=0 is unchanged exploratory NT policy. Zero-sign edges
remain structural only. Effective weights = signed count × .275 mV × .1.
The .1 attenuation is an experimental assumption, not an original Shiu parameter.

## Numerical and runtime audit against Brain/ShiuBaseline/model.py

| Aspect | Old MaleCNSBrain | New variant / Brian2 reference |
|---|---|---|
| Equations/constants | Same intended v/g equations | Rest/reset -52, threshold -45 mV, tau 20/5 ms |
| Integration | Sequential Euler, g decay then v | Coupled exact linear, method=linear |
| Precision | float32 states and pending input | float64 |
| Schedule | Pending input, update, external input, threshold, reset | Update, threshold, synapses/external input, reset |
| Refractory | Decrement before threshold; newly eligible can spike without integration | Tick eligibility gates update and threshold together, 22 ticks |
| Inactive g | Cleared each tick | Frozen; synaptic writes suppressed |
| Stimulated cells | Normal refractory | Zero refractory, matching Shiu Poisson targets |
| External events | Same-tick threshold | Next-tick threshold |
| Delay | 18-slot accumulated input, delivered before update | 18-tick synapses-stage delivery, sparse source queue |
| Reset | v=-52, g=0 | Same; literal reference w=0 is a reset-local temporary, not a synaptic mutation |
| Input generation | NumPy default_rng Bernoulli | Same seeded family for full smoke; deterministic events for parity instead of Brian2 PoissonInput RNG |
| Input amplitude/rate | 250 × .275 mV, selected rate | 68.75 mV, smoke100Hz vs Shiu default150Hz |
| Weight/NT | MaleCNS signed counts and scale | Same assumption, not Shiu FlyWire preprocessing |
| Population | 211577 annotation entities | 166700 annotation-defined neurons |
| Runtime/API | Persistent controller, readout deltas, optional blocked edges | Persistent states/delay and window counts; validation variant, not controller replacement |
| Monitors | Window readout counts | Window counts; full histories only for tiny parity network |
| Parameters | Configurable constants/dt | Validated fixed dt=.1ms; other dt rejected |

Parity covers 10 neurons, excitatory/inhibitory weights, 1.8ms delay, 2.2ms and
zero refractory, repeated events, non-resting initial voltage, all end-of-step
v/g samples and spike ticks over40ms. Acceptance is exact ticks/counts and
maximum state error <1e-8mV. Bounded evidence, not every-network equivalence.

## Full experiment and measurement scope

Existing MaleCNS R upstream mapping is unchanged, checked for membership and
disjointness from readout body10360. Each of three seeds initializes once,
OFF100/STIM100/OFF100, then an extra diagnostic OFF100 without reset.
Old ON100/100/80Hz; new ON100/90/80Hz. First post-OFF10/10/0Hz means immediate
zero is NOT satisfied; examine extra OFF window for transient vs sustained activity.
No forced zeroing of output/state is performed.

The extra OFF100 is 0/0/0Hz: the observed tail ceases by the second OFF window.
Strict zero over the first post-stimulation100ms remains a failed criterion;
do not declare the complete checkpoint accepted without acknowledging this.

Benchmarks use12 persistent OFF/ON/OFF windows, warm11 excluding first.
Wall times cover simulation/counting, not input preparation, loading, transport,
or Unity E2E. Initialization is state allocation only. RSS peak includes graph
construction and Brian2 parity, not runtime-only memory. Mapped payload and
file bytes are separate. All effective CSR arrays are warm-touched; touch page
faults are recorded. Touch does not pin memory or guarantee disk independence.

Server remains on OLD runtime and reports this new model as an unintegrated
validation candidate. Historical results/server_e2e.json ready=true predates
the readiness correction and is not current acceptance evidence.
