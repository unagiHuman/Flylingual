# MaleCNS backend audit (M2-M3)

## Current Windows compiled runtime (2026-09-13)

The Windows runtime requires `pip install -r Brain/MaleCNS/requirements-runtime.txt` with Python 3.10 recommended. The serial float64 Numba kernel compiles the 500-tick window and ordered CSR delivery with `fastmath=False`; initialization prepares the kernel before READY. Numba is required, with no silent fallback. Use the [Windows-local stack](../../Docs/windows/Windows-Local-Stack.md) for normal startup. `ready=false` remains.

The [window-kernel validation](../../Docs/windows/M1-malecns-window-kernel-validation.md) records 168/168 exact windows and 19 passing small tests. Direct mean/p95/max were 101.305/134.074/169.748 ms, reducing the previous implementation's paired mean by 9.934%. Two alternative loop structures were slower and were not adopted. Package/standalone disk-cache restoration also passed in both directions after fixing an import-path startup failure.

The existing Native Player applied 18/18 actions and stopped on TCP disconnection. However, the latest 528-frame trial measured compute p95 323.755 ms/max 671.105 ms, worse than the earlier separate trial; improvement under Unity load is unconfirmed. Compute/frame gaps stayed below 750 ms. A connection-reset background error was logged at shutdown. Walking, microphone input, 15-minute continuity, Mac, and a new Unity build remain unverified.

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
