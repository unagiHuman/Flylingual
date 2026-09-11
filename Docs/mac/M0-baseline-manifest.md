# M0 Mac baseline manifest

Captured 2026-09-11 JST from the protected source trees under `/Users/isaoohta/UnityGame/FlyBrain/Work`.

## Source state

- Unity version: 6000.5.5f1 (`d16e074b49fd`).
- Shiu source repository branch: `main`, tracking `origin/main`.
- The working Shiu repository contained many untracked PoC source/result files. The snapshot includes source files but excludes caches and bulk `results` data.
- Unity Editor was not running when the snapshot was made.

## Preserved runtime inputs

- `Brain/ShiuBaseline/results/codex_run/motor_decoder_calibration.json`
- `Contracts/fixtures/shiu_game_brain_controller_frames.jsonl` (all six actions)
- Shiu connectome inputs remain Git-ignored and require the separate data archive/manifest.

## SHA-256

- `brain_server.py`: `1f495ecb7ea85b4e466e864a84c77d172cc042847eacb808ca4e987c644e735a`
- `brain_controller.py`: `5dd11e3abe3f601e446fa245608ec38749d7bd4136926ee5908aaa3b4dff67b0`
- `poc_config.py`: `3848f147e8999134ffa5aaf48a599a67bccd69aff95c01872871be51929ece3`
- `motor_decoder.py`: `50633700e9d113bd7ece02c9c5ebf8a1f8b738280eb45a67e7d67e841eb84392`
- calibration JSON: `d9ce02e1a853188649dcd96116c7aecf16275b298957271f0d7ae2cc21257e27`
- six-action fixture: `01bb9e218dc62311bf4e91df3fd68a59b6a000fa8a89abd30aa5f4f09e87288a`

## Path resolution

`poc_config.py` resolves connectome inputs and result roots relative to its copied file location. `brain_controller.py` defaults its repository root to its copied file location. `brain_server.py` likewise defaults calibration and run output below the copied tree. The calibration JSON retains an absolute `source_result` provenance string; it is not used to load the decoder.
