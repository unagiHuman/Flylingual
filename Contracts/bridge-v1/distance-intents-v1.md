# distance_intents_v1

2026-09-13。`persistent_intents_v1` を距離指定で拡張する。`bridge_state.capabilities` に `distance_intents_v1` を追加する。既存の Brain 6 Action、BrainFrame、motor、操作権、freshness、安全 inhibit は変えない。

## 内部 proposal

実 Responses の proposal は次の 9 fields を完全一致で返す。追加 field は拒否する。

| field | type / permitted values |
|---|---|
| kind | action / plan / question / clarify / update |
| action | STOP / FORWARD / TURN_R / TURN_L / FORWARD_R / FORWARD_L / null |
| plan | forward_until_concern / right_then_forward / left_then_forward / nudge_right / nudge_left / null |
| validForMs | positive integer or null |
| reply | string, at most 1000 characters |
| operation | new / continue / modify_conditions |
| executionMode | timed / until_next_command / inherit / distance |
| targetExecutionId | null or current execution ID |
| distanceMeters | null or finite number in [0.05, 100] |

`distanceMeters` is null for `timed`, `until_next_command`, and `inherit`. A new `executionMode=distance` requires a permitted distance action or plan, `validForMs=null`, and a non-null `distanceMeters`. It is valid only for actions `FORWARD`/`FORWARD_R`/`FORWARD_L` and plans `forward_until_concern`/`right_then_forward`/`left_then_forward`, with `operation=new` and null `targetExecutionId`. An `update` may use `operation=continue`, `executionMode=distance`, its current `targetExecutionId`, null action/plan, and a non-null `distanceMeters`; that value is the additional distance from the update-time position. STOP, TURN_R, TURN_L, nudge_right, and nudge_left cannot use distance mode.

Questions and clarifications preserve the `persistent_intents_v1` null action/plan rule and have null `distanceMeters`. Existing timed and until-next-command combinations are unchanged. An `inherit` or `modify_conditions` update has null `distanceMeters` and preserves the current distance origin, target, travelled value, remaining distance, and `braking` phase. A spoken additive distance is normalized before execution; a valid current-execution update starts its additional target at the update-time position and resubmits the Action from that new origin. Explicit distance, duration, and until-next-command updates likewise resubmit their Action from a new origin. A duration plus a distance requires `clarify` in v1.

## Observation and execution

`local_safety_observation.travelMeters` is an optional cumulative horizontal distance in Unity metres. `horizontalSpeedMetersPerSecond` is an optional finite, non-negative horizontal speed. Both reset for each epoch and conversation generation, and either is `-1` when unknown. Distance admission requires fresh valid values for both fields; omission remains compatible only with pre-distance operations. Unity accumulates horizontal segments of at least 0.01 m, excludes vertical motion and stationary jitter, and continues accumulating after STOP while measured speed is at least 0.03 m/s. Bridge must not invent travelled distance when it has no valid observation. Odometer regression means a cumulative counter moving backwards, not movement opposite to the facing direction.

For a turn-then-forward plan, distance accumulation begins at its forward phase. A distance execution uses the existing Brain Action path and has `distancePhase=moving` or `braking`. Bridge estimates initial coast as current speed × 1.2 seconds and sends normal STOP early enough to enter `braking`. Completion requires STOP applied, speed below 0.03 m/s, and 0.5 seconds of stable distance. At that point, tolerance is `min(0.5, max(0.15, 0.1 * targetDistanceMeters))` metres and actual travel must be at least `min(0.05, targetDistanceMeters * 0.5)` metres. Only then is `reason=distance_reached` and `completed=true`.

`distance_overshoot`, `distance_shortfall`, `distance_stalled` (less than 0.02 m progress for 8 seconds), and `distance_timeout` (300 seconds) are not completed. STOP confirmation times out after 10 seconds; a missing STOP application or send failure enters the existing inhibit path. No unfinished distance result automatically resubmits FORWARD. Existing safety inhibit applies to hazard, missing/invalid distance or speed, odometer regression, jump, epoch fault, stale, ownership loss, or connection loss.

## state and results

While active, `bridge_state.activeExecution` adds or exposes:

- `executionMode=distance`
- `distancePhase` (`moving` / `braking`)
- `targetDistanceMeters`, `traveledMeters`, `remainingMeters`

On ending, `command_result` has `stage=execution_finished`, `reason` (`distance_reached` / `distance_overshoot` / `distance_shortfall` / `distance_stalled` / `distance_timeout` / `distance_stop_unsettled`), `completed`, and the same three distance fields. The event records execution state; it does not claim a direct motor, CPG, or physics modification. STOP, inhibit, replacement, epoch/generation change, or a fault clears the execution and never revives it.

## Validation status

Implementation and Windows acceptance evidence are recorded in [Distance-Intent-Validation-20260913](../../Docs/windows/Distance-Intent-Validation-20260913.md). The real Player/Brain tests establish movement and continued input, with a recorded short-distance overshoot. They do not establish precision stopping or new microphone acceptance.
