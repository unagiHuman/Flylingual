# MaleCNS backend audit (M2-M3)

## Current Windows compiled runtime (2026-09-13)

The Windows runtime requires `pip install -r Brain/MaleCNS/requirements-runtime.txt` with Python 3.10 recommended. The serial float64 Numba kernel compiles the 500-tick window and ordered CSR delivery with `fastmath=False`; initialization prepares the kernel before READY. Numba is required, with no silent fallback. Use the [Windows-local stack](../../Docs/windows/Windows-Local-Stack.md) for normal startup. `ready=false` remains.

The [fixed-point validation](../../Docs/windows/M1-malecns-fixed-point-validation.md) records 408/408 bit-exact paired windows across three seeds, including five seconds of STOP after stimulation and subsequent stimulation recovery. The kernel preserves signed subnormal conductances whose rounded decay is already unchanged; it substitutes the exact signed-zero product and keeps voltage arithmetic when voltage is not at rest. Runtime coefficient/environment probes disable this optimization when its conditions do not hold. It does not enable FTZ/DAZ or discard small values. The existing 19 tests and eight new boundary/environment tests pass.

The paired direct comparison reduced mean computation from 165.445 to 126.783 ms and p95 from 330.975 to 177.605 ms. Some segments were slower, and transient subnormal arithmetic remains; these are not universal speed or worst-case guarantees. With the existing Native Player and normal CPU affinity, 18/18 actions applied and disconnection stopped output. The 520-window compute profile measured mean/p95/max 174.155/260.308/308.882 ms. Complete Bridge E2E/frame-gap evidence was lost to shared log rotation, and a connection-reset exception was logged during socket close. Walking, microphone input, 15-minute continuity, Mac, and a new Unity build remain unverified by this change.

Earlier [window-kernel validation](../../Docs/windows/M1-malecns-window-kernel-validation.md) and [colocation investigation](../../Docs/windows/M1-malecns-colocation-latency-investigation.md) retain their original results. Their shorter direct workloads do not cover the same aging interval. Package/standalone disk-cache restoration remains covered in both directions.

Earlier neuron-update-only results are retained in [M1 compiled-kernel validation](../../Docs/windows/M1-malecns-compiled-kernel-validation.md).

## Earlier checkpoint history

Current experimental entrypoint: `python Brain/MaleCNS/brain_server_analog.py` from Parallel (50ms only). It uses the validated neuron-only graph and Action-blind EMA100ms plus symmetric turn hysteresis. See [temporal checkpoint](../../Docs/mac/temporal-decoder-checkpoint.md). Five independent seeds, controller equivalence, localhost TCP, and wire Replay passed. `ready=false`: Windows Replay/Live and gameplay latency acceptance remain open. The legacy server below is not the accepted temporal backend. No production synaptic gain or LIF change was made.

New validation-only variant: **Shiu-compatible LIF dynamics applied to the MaleCNS connectome** (`shiu_compatible.py`). This is not official MaleCNS neural dynamics. See [neuron checkpoint audit](../../Docs/mac/neuron-shiu-checkpoint.md). The TCP runtime is not switched to this candidate; `ready=false` remains mandatory.

This directory contains dataset inspection, structural/CSR graph preparation, an experimental persistent NumPy LIF controller, calibration tools, Replay export, and a localhost TCP server. Acceptance is incomplete; `ready=false` is required until the outstanding gates are verified.

The existing 211,577-node graph includes all annotation bodies, including Glia and unresolved classifications. It must not be described as 211,577 verified neurons or a complete physiological CNS model. Effective edges are limited to the explicitly approved ACh/GABA policy.

The NumPy runtime differs from Shiu Brian2 in integration method (Euler-style instead of linear), float precision, scheduling, and refractory handling. Existing measurements describe this particular experimental implementation, not a faithful Shiu port. Validation of the VNC motor pathway, Windows execution, reconnect/error safety, and unbiased holdout calibration remains outstanding.

`run_execution_checkpoint.py --output <path>` runs three sequential 100ms OFF/ON/OFF trials and sequential 25/50/100ms window benchmarks. A separate parent process monitors RSS and terminates its own worker on memory/time budget overrun. The result includes source hashes and dataset hashes.

Run `inspect_dataset.py --help` and `build_sparse_graph.py --help` for the implemented CLI. The downloaded Feather files stay outside Git under `/Users/isaoohta/UnityGame/FlyBrain/Data/malecns/v1.0`.

`config/nt_policy.json` is deliberately strict and unresolved. Therefore the structural graph is not evidence that all edges are dynamically active, and no MaleCNS motor output is ready.

With explicit user approval, `config/nt_policy_exploratory_lif_v1.json` defines a separate PoC policy. `apply_nt_policy.py` creates an edge-aligned `sign.npy` without changing the strict policy. Edges excluded by the exploratory policy remain structural edges but are not dynamically effective.
