# Local Brain Server PoC

This layer keeps the completed 50 ms Cython BrainController unchanged and
exposes it through a localhost TCP server. The protocol is newline-delimited
JSON (NDJSON); each JSON object occupies one line.

```text
Mock Game Client
       | TCP / NDJSON
       v
asyncio Brain Server  -- communication only
       |
       v
single worker thread -- owns BrainController and Brian2 Network
       |
       v
BrainFrame JSON
```

The worker initializes one persistent Network, performs one Cython warm-up
step before advertising `READY`, and then continuously advances 50 ms brain
windows. Action changes never rebuild or reset the Network.

## Start the server

```bash
cd /Users/isaoohta/UnityGame/FlyBrain/Work/Drosophila_brain_model
CC=/usr/bin/clang CXX=/usr/bin/clang++ \
  /Users/isaoohta/miniforge3/envs/brian2/bin/python3.10 \
  brain_server.py --host 127.0.0.1 --port 8765 --backend cython
```

The server uses the saved calibration in
`results/codex_run/motor_decoder_calibration.json` by default. It does not
accept clients until initialization and the cold Cython step have completed.

## Command protocol

```json
{"type":"set_action","requestId":42,"action":"FORWARD_R","clientTimeMs":123456.0}
```

Allowed actions are `STOP`, `FORWARD`, `TURN_R`, `TURN_L`, `FORWARD_R`, and
`FORWARD_L`. Unknown actions return an explicit `error` message and are not
converted to `STOP`.

The server uses latest-action-wins semantics. It keeps one pending command;
new commands overwrite it while a brain step is running. The server records
received and overwritten command counts in each `brain_frame` diagnostics
object and in `brain_server_run.json`.

Each completed brain step publishes a frame containing the applied request
ID, measured DN activity, decoded motor output, and step wall time. The output
is always derived from the whole-brain simulation; the requested action is
never used as a motor-output shortcut.

## Mock client and tests

Interactive command mode accepts `W`, `A`, `D`, `W+A`, `W+D`, `S`, or an empty
line for STOP:

```bash
/Users/isaoohta/miniforge3/envs/brian2/bin/python3.10 \
  mock_game_client.py --mode interactive
```

Latency mode sends 30 sequential action changes and writes:

```bash
/Users/isaoohta/miniforge3/envs/brian2/bin/python3.10 \
  mock_game_client.py --mode latency --count 30
```

This writes `results/codex_run/brain_server_latency.csv` with send time,
applied frame sequence, receive time, end-to-end latency, and brain step wall
time.

The burst test sends `FORWARD`, `FORWARD_R`, `FORWARD_L`, and `STOP` at 20 ms
intervals. It verifies that the final STOP is applied and the middle commands
are not replayed:

```bash
/Users/isaoohta/miniforge3/envs/brian2/bin/python3.10 \
  mock_game_client.py --mode burst
```

The disconnect test closes and reconnects the client, verifies STOP policy,
and checks that `networkRebuildCount` remains 1:

```bash
/Users/isaoohta/miniforge3/envs/brian2/bin/python3.10 \
  mock_game_client.py --mode disconnect
```

The server writes `results/codex_run/brain_server_run.json` when it shuts down.
No Unity, WebSocket, HTTP, C++, or additional neuron search is used here.
