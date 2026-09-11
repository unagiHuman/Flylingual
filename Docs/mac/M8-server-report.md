# M8 experimental server report

Captured 2026-09-11 JST.

`brain_server_malecns.py` exposes the persistent MaleCNS PoC on `127.0.0.1:8766` using TCP/NDJSON. It preserves the six existing Action names, latest-action-wins pending input, `ack`, applied request IDs, and `brain_frame.motor.forward/turn`. Only one controlling client is accepted.

A localhost sequential Mock Client sent STOP, FORWARD, TURN_R, TURN_L, FORWARD_R, and FORWARD_L. All six requests received a frame with the matching `appliedRequestId`. Median E2E was about 1,149 ms and p95/max about 1,177 ms on the final run.

The proposed 500 ms E2E target failed. The server therefore reports `productionReady=false` and `performanceTargetMet=false`. This is a Windows-swappable experimental backend and Replay producer, not an accepted real-time backend. Unity Live integration and Windows execution remain untested.
