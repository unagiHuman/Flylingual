# Bridge v1 protocol

Optional stage speech extension: [blind_run_script_v1](blind-run-script-v1.md).
The Backend consumer is implemented; the Unity sensor/GameFlow producer and live acceptance are not yet verified.
Optional bounded movement plans: [bounded_action_plans_v1](bounded-action-plans-v1.md).
These require fresh local safety observations; missing observations never enable movement.

This is the implemented local-Bridge contract as inspected on 2026-09-12. It
does not certify a Brain, GPT service, Unity scene, or physical behaviour as
ready. The design authority for safety and the external conversation API is
[Brain-GPTLive-CrossPlatform-Design](../../Docs/Brain-GPTLive-CrossPlatform-Design.md).

## Endpoints and ownership

All Bridge listeners bind only to a loopback address. `bridge.tcpPort` defaults
to **8770** and accepts UTF-8 NDJSON for the Unity motor client. The client may
connect only while exactly one local control WebSocket is connected and Bridge
is resumed; otherwise it receives `bridge_control_required_or_inhibited` and is
closed. `bridge.controlPort` defaults to **8771**: `GET /` is the local player
debug page, `GET /player/` serves the separately developed `Runtime/Player`
browser UI, and `GET /ws` is the single control/audio WebSocket. The UI uses
this same origin; a standalone preview on a different port is not authorized
by weakening the origin check. `/player/` serves only public web asset types,
not build scripts, documentation, directory listings, or paths outside Player.
A second control WS
is rejected. Control, conversation text and audio events never enter the Brain
compatible TCP stream.

The Bridge is the only Brain controller. It has one upstream Brain connection;
the Brain wrapper admits one controller session and rejects another with
`controller_already_connected`. A profile determines the target, but its
endpoint may be overridden by the selected terminal-local JSON according to
`CLI > allowlisted environment > local.json > profile > defaults`; therefore a
profile name alone is not an endpoint identity. Remote profiles name a
pre-existing loopback SSH-tunnel endpoint and never create that tunnel.

## Identity, frame and release

The first upstream `status` must contain nonempty `backendId`, `datasetId`,
`configHash`, `graphHash`, `sourceHash`, `instanceId`, and `sessionId`. Bridge
compares all configured expected identity values before treating transport as
connected. `configHash` is SHA-256 of the selected config. `graphHash` is
SHA-256 of canonical JSON (`sort_keys=true`, separators `,`/`:`) mapping these
four filenames to their file SHA-256s: `body_ids.npy`, `indptr.npy`,
`targets.npy`, `weights.npy`. `sourceHash` uses the same canonical aggregate
over these eight source files: `brain_server_bridge.py`, `brain_server_analog.py`,
`brain_server_malecns.py`, `analog_controller.py`, `analog_motor_decoder.py`,
`game_controller.py`, `shiu_compatible.py`, and `temporal_motor_decoder.py`.

`brain_frame` retains the upstream raw BrainFrame. Bridge records it as received;
it does not alter `brain`, `raw`, `motor`, sequence, or upstream
`appliedRequestId`. It requires a strictly increasing `sequence` and matching
`metadata.instanceId`/`metadata.sessionId`. Only a newly received frame updates
freshness. Frame age over **750 ms** is stale; heartbeat, duplicate frame,
conversation state, or ack cannot refresh it.

On a target change or shutdown, Bridge sends an internal negative-ID
`release_controller`. Success requires this exact evidence before another target
can be considered released:

```json
{"type":"controller_released","requestId":-1,"sessionId":"uuid","instanceId":"uuid","activeControllerCount":0}
```

The request ID and both identities must match the current adapter session. No
release evidence is `release_unknown`, remains output-inhibited, and forbids
switch/resume. TCP close alone is not release evidence.

## Control and ID mapping

Allowed actions are `STOP`, `FORWARD`, `TURN_R`, `TURN_L`, `FORWARD_R`, and
`FORWARD_L`. Control accepts an owner (`manual`, `gpt`, or `observer`), monotonic
`controlEpoch`, unique `commandId`, and `validForMs`. `observer` cannot control.
Legacy commands must belong to the current owner/epoch and have a positive finite TTL
not exceeding `maxActionMs` (default 8000 ms). Default action TTL is 4000 ms.
For interpreted player instructions, `maxIntentAgeMs` (default 8000 ms,
positive and at most 8000 ms) independently bounds admission age from the start
of interpretation. Age equal to the limit is expired. Check it again after
awaiting cancellation of an older plan. An admitted action receives its full
`validForMs` from arbiter acceptance; interpretation latency is not subtracted.
STOP retains no movement deadline. This does not promise immediate physical
motion or change Brain-applied confirmation, the timed execution cap, or stale guards.
The opt-in [persistent_intents_v1](persistent-intents-v1.md) capability allows
interpreted GPT movement to use `until_next_command` with no execution deadline.
It retains the independent admission-age limit and all fault/ownership guards.
Continuation and condition updates target a current execution ID and preserve
the current phase; implicit continuation does not reset a timed deadline.
This does not extend manual `set_action` or change the Brain wire protocol.
Epoch changes discard pending intents and delayed responses; they are never
replayed after reconnect or target switch.

`STOP` turns off normal stimulation; it is not an output-safety clearance.
`outputInhibited=true` is separately latched by emergency stop, stale data,
control/Brain transport failure, switching, timeout, or disconnect. It requires
the documented stopped-fresh condition and explicit `resume`; the Unity side
must independently suppress output whenever it sees inhibition or loses its
control route.

Bridge allocates a distinct positive upstream request ID for every accepted
operation. A Unity TCP `set_action` supplies its own **positive** `requestId`;
Bridge maps that value to its upstream request and returns it in downstream ack
and the copied `appliedRequestId` only for the current Unity connection and
epoch. GPT and safety requests have no Unity request ID: their downstream
`appliedRequestId` is **0**, a reserved value that must never be used by Unity.
This mapping changes only downstream fields; the recorded raw BrainFrame is
unchanged.

```json
{"type":"set_action","requestId":41,"action":"FORWARD"}
{"type":"ack","requestId":41,"action":"FORWARD","accepted":true}
{"type":"brain_frame","sequence":19,"appliedRequestId":41,"motor":{"forward":0.3,"turn":0.0}}
```

The ack means the Brain server accepted the stimulus request. A matching
`appliedRequestId` means a Brain frame observed application. Neither proves a
neural outcome nor Unity movement.

## Control WebSocket

The loopback control WS does not negotiate permessage-deflate. Plain WebSocket
frames avoid a reproduced embedded-browser reserved-bit protocol error. Frame
validation, the 128 KiB inbound limit, and origin restrictions remain enabled.

The control WS carries JSON commands such as `emergency_stop`, `set_owner`,
`resume`, `set_action`, `player_text`, `switch_target`, `conversation_start`,
`conversation_stop`, `configure_conversation`, and `audio`. It emits `bridge_state`,
`conversation_options`, `conversation_settings`, `command_result`, raw
`brain_frame`, `brain_summary`, `conversation_state`, `conversation_text`,
`audio`, `discard_audio`, and safe `error` codes. `bridge_state` separates
`brainConnected`, `brainReady` (currently not promoted by this protocol),
`outputInhibited`, reason, owner, epoch, frame age, session/instance, target and
identity hashes. It also carries `conversationSettings`,
`conversationSettingsRevision`, and `resumeReady`. `voiceControlAvailable` is true
only after a fresh voice session starts in the current epoch. An epoch change invalidates voice-derived actions
until explicit conversation stop/start; transcription of old audio must never
operate a new target. Text proposals remain independent of this audio barrier.

`bridge_state.audioDiagnostics` is an optional, counter-only diagnostic object.
The current `ConversationAdapter.diagnostics()` dictionary is the source of
truth for its names and meanings; an older Bridge that does not emit this
field remains protocol-compatible. A current implementation may emit:

```json
{
  "inputChunks": 0,
  "inputBytes": 0,
  "sentInputChunks": 0,
  "sentInputBytes": 0,
  "clockSilenceChunks": 0,
  "inputTranscriptDeltas": 0,
  "outputTranscriptDeltas": 0,
  "outputAudioChunks": 0,
  "outputAudioBytes": 0,
  "outputZeroChunks": 0,
  "outputNonzeroChunks": 0,
  "delegationCount": 0,
  "audioQueueDepth": 0,
  "audioQueueHighWater": 0,
  "audioBackpressureCount": 0,
  "lastErrorCode": null
}
```

`inputChunks`/`inputBytes` count valid PCM input received from the player,
including input rejected because the bounded queue is full; queue rejection is
also counted by `audioBackpressureCount`. `sentInputChunks`/`sentInputBytes`
count successfully sent player-origin PCM, which may itself be silence.
Bridge-generated clock-only silence is separate in `clockSilenceChunks` and is
not player input. Transcript counters
count input and output transcript deltas independently. `outputAudioChunks` /
`outputAudioBytes` count string output-audio deltas and successfully decoded
output bytes respectively; an invalid or empty string delta still increments
`outputAudioChunks`, while it contributes zero decoded bytes. For each nonempty
decoded chunk exactly one of `outputZeroChunks` or `outputNonzeroChunks` is
incremented, with zero/nonzero determined strictly from all decoded PCM bytes.
`delegationCount` counts accepted client-delegation events. Queue depth is the
current bounded queue size, high-water is the maximum observed depth for the
session, and `audioBackpressureCount` counts queue-full rejections.
`lastErrorCode` is a stable safe code or `null`, never an API error message.

The additional delegation/transcript diagnostic set has these ten counters:
`delegationEventsSeen` (raw delegation events),
`delegationRejectedShape`, `delegationRejectedTarget`,
`delegationRejectedId`, `delegationRejectedDuplicate`,
`delegationRejectedOffset` (the five rejection classes),
`timedInputTranscriptDeltas`, `untimedInputTranscriptDeltas`,
`delegationWithTranscript`, and `delegationWithoutTranscript`.
The existing `delegationCount` and `inputTranscriptDeltas` counters remain
separate. Their accounting identities are strict:

```text
delegationEventsSeen = delegationCount
  + delegationRejectedShape + delegationRejectedTarget
  + delegationRejectedId + delegationRejectedDuplicate
  + delegationRejectedOffset
delegationCount = delegationWithTranscript + delegationWithoutTranscript
inputTranscriptDeltas = timedInputTranscriptDeltas + untimedInputTranscriptDeltas
```

`delegationCount` is incremented only after the client-target, bounded ID,
duplicate, and finite-offset checks pass. The timing counters classify input
transcript deltas and do not imply that a delegation was accepted. Counters
reset at live session start; context clearing and conversation stop drain
queued audio while retaining the current session counters. A later session
start creates a new set. No transcript body, PCM, or delegation ID is put in
diagnostics or durable ordinary logs. Bridge-generated voice command IDs may
appear in the server's `voice_intent_dispatch` and `intent_classified`
correlation logs; they are not delegation IDs or transcript content. Any
bounded in-memory delegation ID used solely for duplicate rejection is not
exposed as evidence.

All counters reset when a new live session starts. A context invalidation or
conversation stop drains and discards queued audio but does not retroactively
erase the counters for the session; subsequent session start creates a fresh
counter set. These values are transport/adapter observations only: they do not
prove ASR correctness, Brain application, neural response, or physical body
movement. Conversation text, PCM/audio payloads, and `error.message` are not
stored in this diagnostic object or written to ordinary logs.

Client `audio` messages contain `{type:"audio", audio:"base64 PCM16 mono 24kHz",
controlEpoch:3}`. Stale-epoch audio is rejected before it reaches GPT-Live.
The bounded audio queue is drained separately from control reception, so API
backpressure cannot block receipt of an emergency stop.
While a live conversation is explicitly open, the Bridge supplies paced
100 ms silence when no microphone audio is queued. This keeps the GPT-Live
audio timeline running for typed requests and during echo suppression; it
does not create player speech or neural input. Context invalidation discards
queued microphone audio. Conversation stop cancels the writer entirely.

```json
{"type":"set_action","action":"FORWARD","commandId":"ui-42","controlEpoch":3,"validForMs":1000}
{"type":"bridge_state","epoch":3,"owner":"manual","outputInhibited":false,"frameAgeMs":24,"brainConnected":true,"brainReady":false}
{"type":"command_result","stage":"brain_applied","commandId":"ui-42","requestId":91,"action":"FORWARD"}
```

Audio payloads are base64 PCM only on this local WS and are bounded by the
adapter; audio/transcripts are not persisted by default. The detailed live API
event vocabulary, model choice, and credentials remain isolated in
`ConversationAdapter` and are intentionally not duplicated here. API calls and
Unity audio/visual behaviour are separate gates.

## Conversation presentation settings

On each control-WS connection, Bridge emits this non-secret option message:

```json
{"type":"conversation_options","languages":["ja","en"],"voices":["marin","quartz","ripple","vesper","willow","stone","gleam","meridian","bossa","tempo","beacon","delta","cinder"],"personas":["friendly","curious","calm","custom"],"maxPersonaTextLength":800}
```

The configured settings always contain exactly `language`, `voice`, `persona`,
and `personaText`. Defaults are `ja`, `marin`, `friendly`, and the empty string.
`personaText` is trimmed, limited to 800 characters, and permits normal text
plus newline/tab but not other control characters. It must be nonempty for the
`custom` persona. Unknown keys and invalid values are rejected with stable safe
error codes; the submitted text is not put in an error or ordinary log.

Change settings only with the conversation stopped and Bridge output inhibited, using the
currently advertised `controlEpoch` and `conversationSettingsRevision`:

```json
{"type":"configure_conversation","requestId":"settings-7","controlEpoch":3,"expectedRevision":0,"settings":{"language":"en","voice":"quartz","persona":"curious","personaText":""}}
```

The request is rejected if the control WS is absent, the epoch/revision is old,
the request ID was already used, a conversation/session is still open, output
is not inhibited, switching is in progress, or release is unknown. On success,
Bridge invalidates old context and audio, retains inhibition, increments the
revision, and emits `conversation_settings` with the accepted settings,
revision, and `requiresExplicitStart=true`. It does not resume control or start
conversation automatically. This is a conversation/output-inhibition gate, not
proof that neural motor output has returned to zero. Settings can be changed
without a connected Brain; control resumption still requires the separate
fresh-STOP gate below.

The operator sequence is explicit stop → apply settings → explicit
`conversation_start` → verify `resumeReady` → explicit `resume`. `resumeReady`
is false unless output is inhibited, the Brain adapter is connected, the owner
is non-observer, no switch/release issue exists, a fresh stopped Brain frame is
present, and a `gpt` owner has an open live/mock
conversation. Voice is selected at GPT-Live session startup, so every voice
change requires that new explicit conversation session; it is never changed in
place. Persona affects conversation expression only and is never an Intent
translator input. Language selects the conversation/response language. Neither
changes Brain/decoder values, permissions, control ownership, model selection,
or the Intent translator's allowed-action/safety rules.

These settings are runtime-only. A Bridge process restart resets their revision
and uses the validated terminal-local configuration; it does not restore a
previous WebSocket setting. Voice cloning and voice upload are outside this
contract. Older Bridge or UI implementations that do not implement these
messages are not compatible evidence and must not be reported as configured.

## Current acceptance boundary

Windows Unity must implement independent output inhibition for
`outputInhibited` and control-route loss, then validate positive Unity IDs,
reserved zero, stale handling, release/switching, and actual body observation.
That Windows gate is not implemented or measured by this contract. Mac real
Brain + conversation MOCK results are recorded in
[the integration checkpoint](../../Docs/integration/Bridge-Validation-2026-09-12.md).
Real API text/voice delegation and output with the real Mac Brain are recorded
in [the live checkpoint](../../Docs/integration/Live-Browser-Validation-2026-09-12.md).
Audio hardware, the latest browser UI flow, cross-OS switching, and Unity
behaviour remain separate, unverified gates; `ready=false`.
# Native conversation-only extension (2026-09-12)

`bridge_state.capabilities` advertises `conversation_only_v1`. `conversationMode`
continues to mean API adapter mode (`live/off/mock`). The separate
`conversationInteraction` is `control` (legacy default) or `chat_only`.

Native clients explicitly send `{"type":"conversation_start","interaction":"chat_only","controlEpoch":CURRENT}`.
The Bridge validates the epoch, sets owner `observer`, inhibits body output and
requests safety STOP. It does not wait for Brain readiness/freshness to open the
voice session. No new motor/BrainFrame is synthesized. `ready=false` and 750 ms
freshness semantics are unchanged.

`bridge_state.conversationGeneration` is independent of the physical epoch.
Start, stop, control disconnect and Brain identity replacement advance it.
`audio`, `conversation_text`, `conversation_state` and `discard_audio` carry this
generation. Audio input in chat mode must include integer `conversationGeneration`
matching the active, explicitly started session; otherwise
`old_conversation_generation` is returned. Legacy control audio still requires
`controlEpoch`. Native capture emits 100 ms PCM16LE mono / 24 kHz (4,800 bytes)
as the existing JSON `audio` base64 field.

| State | General audio | Body commands |
|---|---|---|
| chat_only, live, current generation | allowed, including Brain stale/disconnected | rejected |
| chat_only, stopped/stopping/old generation | rejected; queued playback discarded | rejected |
| control (legacy) | previous controlEpoch rules | previous owner/fresh STOP/resume rules |

`resume`, non-observer `set_owner`, `set_action`, text intentions and delegated
intent interpretation cannot execute actions in chat mode (`chat_only_cannot_control`).
The common submit boundary also blocks all non-safety sources. Delegation may
receive a factual “control disabled” reply but never calls the intent translator.
Changing to `control` requires a stopped session and another explicit start;
it does not grant an owner or resume output.

Physical inhibition alone preserves general chat. This initial voice mode receives
no live Brain observation context: neural observations are shown in the Unity
diagnostics, and spoken descriptions must state that current observations are
unavailable. Brain identity replacement/profile switching discards the session and
requires explicit start, preventing old observations from carrying over.

Stop reserves the lifecycle operation immediately, rejects input, discards late
output, cancels a pending start, then closes the API session. Starts during that
operation are rejected (`conversation_already_started_or_stopping`). Native clients
must reject playback locally as soon as Stop is pressed, even before the new
generation arrives. Settings retain the existing stopped/revision/requestId rules.
The single control WebSocket restriction is unchanged.

## Native voice actions extension

An implementation that advertises `native_voice_actions_v1` additionally includes
`conversationStopping` and a loopback-only `motorEndpoint` object in
`bridge_state`. `conversationStopping` is true while the reserved stop lifecycle
operation has not completed. `motorEndpoint` is the configured local Bridge
motor listener, for example `{"host":"127.0.0.1","port":18770}`; it is not
a direct Brain endpoint and does not grant control.

`chat_only` remains a strict no-action mode. A native client can opt into the
existing control path only by sending a stopped-session start with every field
below:

```json
{"type":"conversation_start","interaction":"control","nativeVoiceControl":true,"controlEpoch":7}
```

`nativeVoiceControl` must be JSON boolean `true`, `interaction` must be
`control`, and `controlEpoch` must be an integer equal to the current epoch.
The Bridge sets owner `gpt`, inhibits with `native_voice_control`, sends the
existing safety STOP, and then starts the existing control conversation. This
does not resume output. The client must still observe the current fresh stopped
BrainFrame, wait for `resumeReady`, and send explicit `resume`. If a `resume`
message includes `controlEpoch`, it too must be an integer matching the current
epoch; legacy resumes may omit that field.

Control-mode native audio continues to require the current `controlEpoch`.
When it includes `conversationGeneration`, that value must be an integer equal
to the current accepting session; stale or stopping-session audio is rejected.
Delayed audio and conversation text are dropped once any conversation is no
longer accepting. These additions do not change `ready=false`, the 750 ms
freshness boundary, action TTL, voice-session epoch barrier, or the raw
BrainFrame/motor decoder path.

## Experimental visual threat extension (2026-09-14)

Only Brain status capability `visual_threat_v1` enables this optional path.
The normal six Action commands and `appliedRequestId` retain their meaning.
The Bridge maps one accepted, fresh `threat_started` from the existing swatter
environment source to one fixed LC4/LPLC2 pulse. This is `event_proxy_v1`, not
a retinal angular-size/velocity model or evidence of fear/aversion.

```json
{"type":"set_visual_threat","requestId":-1,"active":true,"validForMs":749}
{"type":"visual_threat_ack","requestId":-1,"accepted":true,"active":true}
```

The request has exactly those four fields. ON uses an integer TTL of 1–750
wall-clock milliseconds; OFF uses `active:false, validForMs:0`. Receipt sets
the server deadline before worker scheduling. Bridge subtracts environment
age and socket-lock waiting time before writing. A pulse is also capped at
500 ms of brain time and cannot renew from the same warning. Request IDs use
one direction per TCP session: negative IDs strictly decrease (Bridge internal
IDs), nonnegative IDs strictly increase. Duplicates or reversed IDs are rejected.
Sensory acknowledgement means acceptance, not proof of neural application.

STOP atomically cancels the pending sensory slot even when a later movement
command supersedes that STOP. Release/disconnect invokes the same cancellation.
The current 50 ms brain window finishes before cancellation takes effect; wall
expiry is checked at window boundaries. Thus cancellation/expiry can include
one already executing window of latency. OFF does not imply zero residual firing.
Epoch, conversation generation, run/attempt, stale state and input inhibition
invalidate pending Bridge writes and old observations. Warning end/cancel,
fall and swatting request OFF. Capability absence sends no sensory request.

`brain_frame.raw.visualThreat` contains exactly `schemaVersion:1`,
`stimulusModel:"event_proxy_v1"`, `active`, `inputEventCount`, `requestId`,
`reason`, and `readouts`. `readouts.R` is bodyId 10001 and `.L` is 10010;
each has integer `spikeCount` and `rateHz = spikeCount * 1000 / windowMs`.
`active` refers to the measured window, and positive `inputEventCount` proves
external events were applied. Counts are measured outputs, not Action-derived
motor values. Input selection is fixed at the audited 126 LC4 and 185 LPLC2
cells; clients cannot select IDs, rate or strength.

The control WebSocket emits `visual_threat_observation` with the unchanged `raw`,
`evidenceSource:"brain_frame"`, `stimulusModel`, `windowMs`, `inputValidForMs`,
`brainSequence`, `brainSessionId`, `brainInstanceId`, `controlEpoch`,
`conversationGeneration`, `sourceId`, `environmentSequence`, `runId`, `attempt`,
`ageMs`, `staleAfterMs` and `fresh:true`. Scope and freshness are checked again
when dequeued; malformed sensory observations are discarded independently of
movement. GPT receives bounded Japanese/English factual context on input-state
changes, subject to speech/intent gates. `environment_observation` remains a
separate environment fact with `neuralInputApplied:false`; only the measured
sensory observation describes neural application. `ready=false` and the
unconfigured affective proxy remain unchanged.

### Measured commentary receipts

The first positive DNp01 window of a warning can be retained as explicitly
historical evidence for at most 8 seconds. Its age never refreshes from later
frames. The existing accepted warning-clear scene line may include those
recorded rates once, in Japanese/English; it does not add a separate speech
request. Current Brain freshness, identity, epoch, conversation
generation and run must still match. Inhibition, disconnection, context clear,
or expiry discards it; normal STOP cancels input but does not erase that recent
measurement. Existing scene-cue permission and deduplication still apply;
reduced-commentary preferences and disabled neural feedback suppress this
addition. Warning and movement commands are not replaced. This
does not extend the 750 ms current-observation freshness rule.

For traced appends the local log `conversation_context_receipt` records
`stage:sent|accepted|unmatched`, event ID, channel, context generation, content
SHA-256 and an allowlisted observation trace, never the content or audio.
`sent` means transport send completed. `accepted` requires a matching current
API acknowledgement (matching `client_event_id` and channel, or `event_id`
only when `client_event_id` is absent); unknown or absent IDs remain
`unmatched`. Receipt storage is capped at 128 records, correlation expires
after 30 seconds, and storage is
cleared at context reset, stop or stream termination. Neither send nor
acceptance alone proves an audible, scientifically accurate utterance; real
Player transcripts must be compared separately against the original window.
