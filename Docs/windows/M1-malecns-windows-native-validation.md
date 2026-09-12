# MaleCNS Windows native runtime check

Date: 2026-09-12 JST
Repository baseline: 5d741284f9633c8667c258184893b3aafaa5b5a2
Result: BLOCKED — portable graph files unavailable in the checked locations.

## Executed

- Created independent Windows CPython 3.10.12 x64 environment at `artifacts/windows-malecns/.venv`.
- Installed and imported exact runtime dependencies: NumPy 1.24.3, psutil 7.2.2.
- `brain_server_analog.py --help`: successful.
- `verify_analog_assets.py`: failed on missing body_ids.npy.
- Actual server startup with `--host 127.0.0.1 --port 8766 --window-ms 50`: exited 1 during controller initialization with FileNotFoundError for body_ids.npy. Failure occurred before TCP listen.
- Searched Downloads and the old/new repository workspace for the four graph filenames: none found. Other storage locations were not exhaustively searched.

## Required next input

Copy the validated Mac `artifacts/neuron_checkpoint/` portable numeric files into this repository's `artifacts/neuron_checkpoint/`:

- body_ids.npy (1,333,728 bytes)
- indptr.npy (1,333,736 bytes)
- targets.npy (78,682,904 bytes)
- weights.npy (157,365,680 bytes)

Total: 238,716,048 bytes. Expected SHA-256 values are in `Brain/MaleCNS/config/analog_handoff_manifest.json`. Verify hashes before execution. These files are intentionally excluded from Git; InitialCommit did not include them.

## Scope and evidence

No Mac connection, Unity launch, model/decoder/physics changes, or synthetic replacement graph. No WSL requirement established. BrainFrame generation, six actions, TCP exchange, performance and Windows-only gameplay remain NOT_RUN. ready=false remains unchanged.

Raw evidence: `artifacts/windows-malecns/environment.txt`, `server-help.txt`, `verify-assets.txt`, `server-start.txt`.

After data arrival: asset verification, localhost server, one mock client STOP then six actions, normal disconnect; Unity follows only after the brain runtime passes.

## Follow-up: validated graph received; native execution confirmed

All four supplied NPY files matched the handoff SHA-256 hashes. Full verify_analog_assets.py also passed repository/config/Replay checks. Data is now in artifacts/neuron_checkpoint (Git ignored).

Actual Windows native server started on 127.0.0.1:8766. A single mock client received 63 real BrainFrames, increasing sequence, backend MALECNS_EXPERIMENTAL, ready=false, protocol errors 0. Initial STOP and five moving actions passed stable last-four-frame motor sign checks. Normal client disconnect succeeded. A subsequent connection received status and four zero STOP frames with continuing sequence, then disconnected normally.

Performance: first stream frame 932.71ms; corresponding action frame 3114.63–4535.96ms; mean 50ms simulation window took 2026.31ms wall time. Final STOP first near-zero motor was 13449.44ms after sending STOP. The original eight-frame test exited 1 because its last four STOP values contained forward=0.0259 followed by three zeros; this strict criterion was NOT changed or relabeled PASS. Later reconnect confirmed sustained zero motor, but does not improve the measured STOP latency.

Conclusion: Windows-only MaleCNS brain execution and localhost transport confirmed; latency/gameplay acceptance remains unpassed. Unity was not launched in this check. Existing 750ms Unity stale threshold is substantially shorter than the observed mean frame interval; do not claim plug-and-play Unity acceptance or silently extend it. No Brain/decoder/physics changes. Test server was terminated after both clients disconnected. ready=false retained.

Evidence: artifacts/windows-malecns/verify-assets-with-data.txt, server-with-data.txt, native-six-actions.json, native-reconnect.json, native-summary.json. UTC timestamps are stored as reported by the Windows clock; local task date is 2026-09-12 JST.
