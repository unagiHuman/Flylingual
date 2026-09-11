# Existing Shiu TCP/NDJSON contract

This records the copied baseline implementation as inspected on 2026-09-11. It is descriptive, not a proposed MaleCNS schema.

## Transport and ownership

- TCP with one UTF-8 JSON object per newline.
- Default endpoint is `127.0.0.1:8765`.
- One worker thread owns the persistent Brian2 controller.
- Commands are latest-action-wins. A pending command may be overwritten before a step.
- Frames are broadcast to every connected session. The current server does not enforce a single controlling client, so operation must restrict control to one client.
- When the last client disconnects, the worker queues `STOP`.

## Client messages

The implemented command is `set_action` with required `requestId`, required `action`, and optional `clientTimeMs`.

Allowed actions are `STOP`, `FORWARD`, `TURN_R`, `TURN_L`, `FORWARD_R`, and `FORWARD_L`.

Accepted commands receive an `ack` containing `requestId`, normalized `action`, and `accepted=true`. Invalid JSON, invalid message type, missing request ID, and unknown action receive an `error` message.

## Server messages

On connection, the server sends `status` with `state=READY`, backend, window and dt values, and network rebuild/reset counts.

Each `brain_frame` contains:

- monotonically increasing `sequence` from the persistent controller;
- `appliedRequestId` and `appliedClientTimeMs`, populated only on the step that consumes a pending command;
- `requestedAction`, identifying the action active for that step;
- `brainTimeMs`;
- `motor.forward` and `motor.turn`;
- Shiu-specific `brain` readouts (`DNp09_Hz`, `DNa02_R_Hz`, `DNa02_L_Hz`, `DNa02Difference_Hz`);
- `performance.windowMs` and `performance.stepWallTimeMs`;
- command diagnostics.

The Unity actuator reads only `motor.forward/turn`. Its copied scenes use a 0.75-second stale-frame timeout. The existing Python server has no backend-metadata message and no explicit LIVE/REPLAY/SHIU label beyond its backend field; those are future integration work, not baseline behavior.

## Known baseline constraints

- The wire format has protocol version 1 only in the shutdown summary, not every live frame.
- Unknown JSON fields are not part of the current Python command validation.
- `brain_server.py` contains the `requestedAction` key twice in the Python literal with the same value; Python retains one key in serialized output. The frozen baseline is intentionally not altered here.
- The recorded fixture contains all six actions and is Shiu/FlyWire-specific. Its IDs and calibration must not be reused for MaleCNS.
