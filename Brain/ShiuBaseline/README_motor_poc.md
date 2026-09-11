# Descending-neuron motor-output PoC

This PoC keeps the upstream `model.py` unchanged.  It adds an explicit
v630/v783 dataset configuration, a thin simulation/rate adapter, and a
provisional decoder that writes `motor_output_100Hz.json` and
`motor_output_200Hz.json`.

## Architecture findings

1. The Sugar FlyWire root IDs are passed to `model.run_exp` as `neu_exc`.
   `run_exp` maps each root ID to a Brian index using the completeness CSV.
2. `model.create_model` loads the connectivity parquet, constructs a Brian2
   `Synapses`, and connects `Presynaptic_Index` to `Postsynaptic_Index`.
3. `run_trial` records spikes with `SpikeMonitor`; `construct_dataframe` emits
   `t`, `trial`, `flywire_id`, and `exp_name`; `run_exp` writes parquet.
4. `utils.load_exps` reads parquet and `utils.get_rate` computes mean and
   standard-deviation firing rates across trials.
5. Dataset selection is explicit in `poc_config.py`: `v630` uses the original
   630 CSV/parquet names and `v783` uses `Completeness_783.csv` and
   `Connectivity_783.parquet`.
6. The upstream model rebuilds the full `NeuronGroup`, `Synapses`, and
   `SpikeMonitor` once per trial.  The new adapter isolates that boundary for
   a future persistent brain, without changing the upstream code.

The v783 files contain root IDs and connectivity columns but no
neurotransmitter annotation, so neurotransmitter output is reported as
unavailable rather than inferred.

## Run

```bash
cd /Users/isaoohta/UnityGame/FlyBrain/Work/Drosophila_brain_model
conda activate brian2
python run_motor_poc.py --dataset v783 --n-run 3 --frequencies 100 200
```

The v783 run writes simulation parquet under `results/codex_run/v783/`, motor
JSON under `results/codex_run/`, and the target-neuron table to
`results/codex_run/descending_activity_v783.csv`.

The current v783 materialization is missing Sugar ID `720575940620900446`.
The runner skips that ID and logs it; it does not invent a replacement ID.

The decoder uses explicit parameters:

- `forward_scale_hz`: DNp09 rate mapped to `forward=1.0`
- `turn_scale_hz`: DNa02 right-minus-left rate mapped to `turn=1.0`

Both can be overridden on the command line.  This is a provisional decoder,
not a biological motor-control claim.

## Mac brain-only input-change proof

The Unity-independent proof compares all available Sugar IDs against the
first half of the same IDs at one frequency and trial count:

```bash
python run_brain_input_change_poc.py --dataset v783 --n-run 10 --frequency-hz 100
```

It writes `results/codex_run/mac_brain_input_change_evidence.json`. This
checks that changing the sensory input changes downstream spike rates. It
does not claim that the selected descending neurons are already a reliable
motor signal; that remains a separate validation gap.

## Motor-related DN path search

The coarse-to-fine search is reproducible with:

```bash
python run_motor_dn_screening.py --dataset v783 --frequency-hz 100 --n-run 1 --group-size 5
python run_motor_dn_revalidation.py --dataset v783 --frequency-hz 100 --n-run 5
```

The first command ranks direct presynaptic candidates, runs a no-stimulation
baseline, and screens one top-five group per target. The second command
re-runs only those promising groups and records per-trial rates and DNa02
left/right differences.

The selected groups are direct one-hop inputs to their target DNs. No
neuron-name annotation was available in the v783 materialization, so names
are left blank. The fixed, Unity-independent result is
`results/codex_run/brain_motor_poc.json`; it contains the reproducible
DNa02_R condition plus the DNa02_L and DNp09 alternatives.

## Persistent-brain smoke test

The fixed `top5_DNa02_R` group can be switched on and off inside one
continuously running network:

```bash
python run_persistent_brain_smoke.py --dataset v783 --stimulus-frequency-hz 100 --phase-ms 500 --step-ms 100
```

This produces `results/codex_run/persistent_brain_smoke.json` and the
incremental `persistent_brain_smoke.jsonl`. The network is built once,
advances for 15 steps, uses NumPy codegen, and records cumulative-count
differences rather than an unbounded whole-brain spike history. Candidate
neurons keep the official `rfc=0 ms` behavior for the whole run; OFF only
sets the input rate to zero and does not reset state.

## Cython benchmark

Brian2 2.5.1 was incompatible with the initially installed Cython 3.2.9
because that version no longer exports `Cython.Utils.get_cython_cache_dir`.
The minimal environment fix was to install Cython 0.29.37, set
`CC=/usr/bin/clang` and `CXX=/usr/bin/clang++`, and place the Brian2 Cython
cache under `results/codex_run/cython_cache`.

The persistent smoke test supports both backends:

```bash
python run_persistent_brain_smoke.py --backend numpy --seed 20260910 \
  --output results/codex_run/persistent_benchmark_numpy_final.json
CC=/usr/bin/clang CXX=/usr/bin/clang++ \
  python run_persistent_brain_smoke.py --backend cython --seed 20260910 \
  --output results/codex_run/persistent_benchmark_cython_final.json
```

The Cython run keeps the same model, dt, stimulus, seed, and 15-step
sequence. Its result and the NumPy result can be compared directly.

## Brain controller state sequence and window benchmark

The fixed upstream groups can be switched in one persistent session with the
actual sequence `OFF, R, OFF, L, OFF, F, OFF, F+R, OFF, F+L, OFF`:

```bash
CC=/usr/bin/clang CXX=/usr/bin/clang++ \
  python run_brain_controller_sequence.py --backend cython --seed 20260910 \
  --step-ms 100 --output results/codex_run/brain_controller_sequence_cython_100ms.json
```

The same session implementation was benchmarked at 25, 50, 100, and 200 ms
windows. Each phase remains 500 ms; the 200 ms case records a final 100 ms
remainder step so that the phase duration is not changed. Results are in
`results/codex_run/brain_window_benchmark_cython.csv` and phase-level DN
activity is in `brain_controller_phase_summary.csv`.

## Game brain controller PoC

The next layer exposes six game actions while keeping the same whole-brain
network alive:

```text
STOP       -> no stimulation
FORWARD    -> F (top5_DNp09)
TURN_R     -> R (top5_DNa02_R)
TURN_L     -> L (top5_DNa02_L)
FORWARD_R  -> F + R
FORWARD_L  -> F + L
```

The controller changes only the upstream Poisson rates. It does not rebuild
the network or reset neuron, synapse, or refractory state on an action change.
The motor decoder consumes the measured DN rates; it never substitutes a
requested action for a brain output.

The decoder calibration is derived from the measured 50 ms controller
sequence. The forward reference is the 95th percentile of DNp09 activity in
F/F+R/F+L windows. The turn reference is the 95th percentile of the absolute
DNa02 right-minus-left difference in R/L/F+R/F+L windows. The straight-state
dead zone is the 95th percentile of the absolute DNa02 difference in F windows
plus one-quarter of one-spike rate resolution (5 Hz at 50 ms).

Run the 50 ms continuous controller test with Cython:

```bash
cd /Users/isaoohta/UnityGame/FlyBrain/Work/Drosophila_brain_model
CC=/usr/bin/clang CXX=/usr/bin/clang++ \
  /Users/isaoohta/miniforge3/envs/brian2/bin/python3.10 \
  run_game_brain_controller_poc.py --backend cython --window-ms 50
```

Outputs are `results/codex_run/game_brain_controller_frames.jsonl`,
`results/codex_run/game_brain_controller_summary.csv`, and
`results/codex_run/motor_decoder_calibration.json`. A run-level JSON summary
is also written to `results/codex_run/game_brain_controller_run.json`.
