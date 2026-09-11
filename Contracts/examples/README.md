# Existing Shiu protocol examples

These examples use only fields implemented in `Brain/ShiuBaseline/brain_server.py`.
They are debug inputs, not evidence of a Windows Live run.

- `set_action.json`: illustrative valid STOP request; optional clientTimeMs omitted.
- `brain_frame.json`: first recorded frame projected by `tools/normalize_shiu_replay.py`.
  Missing command IDs, client time and diagnostics are null, not fabricated zeros.
- `status.json`: illustrative READY message using the server's default backend/window
  and controller initialization counts. `dtMs` is deliberately null because no
  live server clock was measured for this example. A real initialized server
  reports a numeric dtMs; this is a missing-value debug case, not a captured status.
- `error.json`: exact missing-request-ID response from `_handle_command_line`.

The normalized recording has the server frame shape, but nullable missing
measurements are an offline adaptation, not a guarantee that Live emits null
in every numeric field. Consumers must distinguish null/missing from measured
zero. No protocolVersion, backend metadata or REPLAY label is invented inside
brain_frame: those are not fields emitted by the existing server. The replay
source/HUD must explicitly identify this as REPLAY (Shiu recording).

Normalization maps brainSimulationTimeMs to brainTimeMs, moves the four recorded
rates into brain and the two recorded timings into performance, and preserves
sequence, requestedAction and motor. It never derives a missing difference rate,
motor, request ID or sequence. Controller-only phase, stimulus IDs, spike counts,
backend and decoder information remain in the unmodified source fixture.

Run from the repository root with any Python 3.10+ standard-library runtime:

```powershell
python tools/normalize_shiu_replay.py
python -m unittest discover -s tools -p 'test_normalize_shiu_replay.py' -v
```

The script prints source/output SHA-256 and frame count. Regeneration must match
the checked-in fixture byte for byte; all six action counts and all recorded
motor/rate/timing values are covered by the tests. This verifies data conversion,
not Unity playback, physics, HUD rendering or Live TCP behavior.
