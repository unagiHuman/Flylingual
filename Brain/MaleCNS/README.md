# MaleCNS backend audit (M2-M3)

## Current Windows compiled runtime (2026-09-13)

The Windows runtime now requires `pip install -r Brain/MaleCNS/requirements-runtime.txt` with Python 3.10 recommended. It uses the serial float64 Numba LIF kernel with `fastmath=False`; the first JIT compile occurs before READY. Numba is required and there is no silent fallback. Numerical equivalence and direct timings are recorded in [M1 compiled-kernel validation](../../Docs/windows/M1-malecns-compiled-kernel-validation.md). The compiled 168-window result is not a Unity/TCP acceptance result; `ready=false` remains.

The 2026-09-13 existing Native Player trial reached 18/18 Brain action applications with no 750 ms compute or frame-gap stop, but it did not demonstrate walking; microphone, 15-minute continuity, and a new Unity build remain untested.

Current experimental entrypoint: `python Brain/MaleCNS/brain_server_analog.py` from Parallel (50ms only). It uses the validated neuron-only graph and Action-blind EMA100ms plus symmetric turn hysteresis. See [temporal checkpoint](../../Docs/mac/temporal-decoder-checkpoint.md). Five independent seeds, controller equivalence, localhost TCP, and wire Replay passed. `ready=false`: Windows Replay/Live and gameplay latency acceptance remain open. The legacy server below is not the accepted temporal backend. No production synaptic gain or LIF change was made.

New validation-only variant: **Shiu-compatible LIF dynamics applied to the MaleCNS connectome** (`shiu_compatible.py`). This is not official MaleCNS neural dynamics. See [neuron checkpoint audit](../../Docs/mac/neuron-shiu-checkpoint.md). The TCP runtime is not switched to this candidate; `ready=false` remains mandatory.

This directory contains dataset inspection, structural/CSR graph preparation, an experimental persistent NumPy LIF controller, calibration tools, Replay export, and a localhost TCP server. Acceptance is incomplete; `ready=false` is required until the outstanding gates are verified.

The existing 211,577-node graph includes all annotation bodies, including Glia and unresolved classifications. It must not be described as 211,577 verified neurons or a complete physiological CNS model. Effective edges are limited to the explicitly approved ACh/GABA policy.

The NumPy runtime differs from Shiu Brian2 in integration method (Euler-style instead of linear), float precision, scheduling, and refractory handling. Existing measurements describe this particular experimental implementation, not a faithful Shiu port. Validation of the VNC motor pathway, Windows execution, reconnect/error safety, and unbiased holdout calibration remains outstanding.

`run_execution_checkpoint.py --output <path>` runs three sequential 100ms OFF/ON/OFF trials and sequential 25/50/100ms window benchmarks. A separate parent process monitors RSS and terminates its own worker on memory/time budget overrun. The result includes source hashes and dataset hashes.

Run `inspect_dataset.py --help` and `build_sparse_graph.py --help` for the implemented CLI. The downloaded Feather files stay outside Git under `/Users/isaoohta/UnityGame/FlyBrain/Data/malecns/v1.0`.

`config/nt_policy.json` is deliberately strict and unresolved. Therefore the structural graph is not evidence that all edges are dynamically active, and no MaleCNS motor output is ready.

With explicit user approval, `config/nt_policy_exploratory_lif_v1.json` defines a separate PoC policy. `apply_nt_policy.py` creates an edge-aligned `sign.npy` without changing the strict policy. Edges excluded by the exploratory policy remain structural edges but are not dynamically effective.
