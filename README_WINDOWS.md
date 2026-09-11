# Windows handoff

## Stage 1: Unity and replay

Clone `main` to receive the frozen Shiu source and Unity project. Open `UnityProject` with Unity 6000.5.5f1. Use `Contracts/fixtures/shiu_game_brain_controller_frames.jsonl` for the established Shiu six-action replay.

The `feat/malecns-loader` branch additionally provides `Contracts/fixtures/malecns_poc_holdout_seed_20260913.jsonl`. It contains current nested `brain_frame` objects with all six actions and calibrated motor output. It is marked `mode=REPLAY`; it is not proof that the Windows Live backend meets performance acceptance.

## Stage 2: rebuild MaleCNS data and graph

Use a fresh Python 3.10 environment. Install Visual Studio Build Tools/MSVC separately if the Shiu/Brian2 Cython backend is needed. Do not reuse Mac clang variables, conda directories, `.dylib`, `.so`, or Cython caches.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r Environment\requirements-windows.txt
python Brain\MaleCNS\tools\download_malecns.py --out Data\malecns\v1.0 --only all
```

Verify the downloaded byte counts and SHA-256 values against `Brain/MaleCNS/results/download_manifest.json`, then generate the structural and runtime graphs:

```powershell
python Brain\MaleCNS\build_sparse_graph.py --data Data\malecns\v1.0 --output artifacts\malecns_structural_graph --work artifacts\malecns_graph_work
python Brain\MaleCNS\apply_nt_policy.py --graph artifacts\malecns_structural_graph --nt Data\malecns\v1.0\body-neurotransmitters-male-cns-v1.0.feather --policy Brain\MaleCNS\config\nt_policy_exploratory_lif_v1.json --output artifacts\malecns_signed_graph
python Brain\MaleCNS\build_effective_csr.py --graph artifacts\malecns_structural_graph --signed artifacts\malecns_signed_graph --output artifacts\malecns_effective_csr
```

## Experimental Live server

```powershell
python Brain\MaleCNS\brain_server_malecns.py --graph artifacts\malecns_effective_csr --mapping Brain\MaleCNS\config\game_mapping_exploratory_v1.json --calibration Brain\MaleCNS\results\motor_decoder_calibration.json --host 127.0.0.1 --port 8766
```

The server preserves the existing `set_action`, `ack`, and `brain_frame.motor.forward/turn` meanings and identifies itself as `malecns_lif_poc` / `male-cns:v1.0`. It accepts one controlling client. The measured Mac localhost E2E p95 is about 1.18 seconds, so `productionReady=false` and `performanceTargetMet=false`. Keep Replay available and do not relabel this as a production-ready or biologically validated MaleCNS emulator.

Large official Feather files and generated arrays remain outside Git. Unity `Library`, `Temp`, `Build`, caches, and machine-specific environments must also remain outside Git.
