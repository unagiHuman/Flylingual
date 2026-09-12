# MaleCNS buffer reuse diagnostic

Production Brain/decoder/Unity files unchanged. Candidate exists only in the diagnostic harness and ignored artifacts.

## Line timing

Original.step, one initial STOP output window with Python tracing: membrane update line 33 = 1.209s; conductance decay line 34 = .273s; active mask line 32 = .213s. Tracing has overhead; these measurements identify hotspots, not uninstrumented timings. Lines 33/34 use repeated boolean-index gathers and scatter writes.

## Candidate

Replace only the two indexed state-update statements with two reusable float64 buffers, NumPy ufunc out parameters, np.copyto(where=active), and masked in-place conductance decay. Preserve arithmetic ordering, refractory gating, spike threshold/reset, delayed synapse scheduling and accumulation, all model constants, decoder and controller. Inactive scratch entries are computed but never copied to model state.

## Paired comparison

Seed 20270101, 50ms windows, dt .1ms, original graph/config. Separate original/candidate controllers, identical initialization. 28 uninstrumented windows: four each STOP/FORWARD/TURN_R/TURN_L/FORWARD_R/FORWARD_L/STOP. Execution order alternates to reduce ordering bias.

- Original mean: 2357.81ms.
- Candidate mean: 802.61ms.
- Ratio: 2.94x faster (about 66% less time).
- All 28 comparisons passed exact np.array_equal for v/g/last/rfc at window boundaries; tick/pending spikes/RNG state matched; every BrainFrame field excluding performance timing matched exactly.
- Initialization and one separately instrumented STOP window also passed state equivalence.

This is one seed and a short input sequence, not exhaustive numerical or gameplay acceptance. Four windows per action are not the settled eight-window action gate. Record=True is not exercised. Mac hardware was not rerun; the remaining gap with its stored .4s mean is unexplained. Timing varies across runs; compare paired numbers, not earlier standalone means.

## Next step

Candidate is promising but not installed in production. Before adopting: more seeds/longer switching and STOP recovery equivalence, then actual localhost TCP latency and Unity stale/gameplay checks. Candidate mean .80s still exceeds the existing .75s stale threshold, so this result alone does not establish usable Unity Live. No threshold, power setting, neural value or decoder change was made.

Reproduce: artifacts/windows-malecns/.venv/Scripts/python.exe tools/probe_malecns_buffers.py
Results: Docs/windows/M1-malecns-buffer-results.json. Raw candidate/line timings/comparisons: artifacts/windows-malecns/buffer-probe/.
