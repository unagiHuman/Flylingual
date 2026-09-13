using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Globalization;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>
    /// Unity voice endpoint. Explicit voice control uses the Bridge's fresh STOP/resume gate.
    /// A bootstrap must explicitly call ConnectAsync; Awake/Start deliberately do not connect.
    /// </summary>
    public sealed class ConversationSessionController : MonoBehaviour
    {
        const string DefaultUrl = "ws://127.0.0.1:18771/ws";
        const int MaximumMainThreadMessages = 256;
        const int MaximumMessagesPerUpdate = 64;
        readonly ConcurrentQueue<Action> mainThread = new ConcurrentQueue<Action>();
        BridgeConversationSocket transport;
        CancellationTokenSource cancellation;
        UnityMicrophoneCapture microphone;
        UnityReplyAudioPlayer replyAudio;
        int requestNumber;
        bool requestedStart;
        bool autoStartPending = true;
        bool captureAttempted;
        string expectedSettingsRequestId;
        string selectedDevice;
        string captionRole;
        int mainThreadCount;
        int connectionAttempt;
        Coroutine enableActionsRoutine;
        bool bodyArmed, resumePending, bridgeConnected, voiceControlAvailable, resumeReady, conversationStopping;
        int armedEpoch;
        string bridgeConversationState;
        double frameReceivedAt = double.NegativeInfinity, stateReceivedAt;
        readonly Dictionary<int, string> pendingActions = new Dictionary<int, string>();

        [SerializeField] UnityMicrophoneCapture microphoneCapture;
        [SerializeField] UnityReplyAudioPlayer replyAudioPlayer;

        public string Status { get; private set; } = "disconnected";
        public string Error { get; private set; }
        public bool Ready { get; private set; }
        public int ConversationGeneration { get; private set; } = -1;
        public string ConversationInteraction { get; private set; } = "chat_only";
        public int ControlEpoch { get; private set; }
        public string Owner { get; private set; } = "observer";
        public bool OutputInhibited { get; private set; } = true;
        public bool ConversationLive { get; private set; }
        public bool IsSessionRequested => requestedStart;
        public string Caption { get; private set; } = string.Empty;
        public string LastSettingsResult { get; private set; } = string.Empty;
        public int SendQueueDepth => transport == null ? 0 : transport.QueueDepth;
        public float InputRms => microphone == null ? 0f : microphone.Rms;
        public int BufferedMilliseconds => replyAudio == null ? 0 : replyAudio.BufferedMilliseconds;
        public long PlayedSamples => replyAudio == null ? 0L : replyAudio.PlayedSamples;
        public int Underruns => replyAudio == null ? 0 : (int)replyAudio.Underruns;
        public string AudioError => microphone == null ? (replyAudio == null ? null : replyAudio.Error) : microphone.Error ?? (replyAudio == null ? null : replyAudio.Error);
        public string[] Devices => microphone == null ? Array.Empty<string>() : microphone.Devices;
        public int SampleRate => microphone == null ? 0 : microphone.SampleRate;
        public float Volume => replyAudio == null ? 0f : replyAudio.Volume;
        public ConversationSettings Settings { get; private set; } = new ConversationSettings();
        public int SettingsRevision { get; private set; }
        public ConversationOptions Options { get; private set; } = new ConversationOptions();
        public string Backend { get; private set; }
        public bool BrainReady { get; private set; }
        public float FrameAgeMs { get; private set; }
        public long Sequence { get; private set; }
        public string SchemaError { get; private set; }
        public long ReceivedAudioBytes { get; private set; }
        public long ReceivedNonzeroAudioBytes { get; private set; }
        public long ReceivedTranscriptDeltas { get; private set; }
        public long SentAudioChunks { get; private set; }
        public long SentAudioChunksDuringReply { get; private set; }
        public bool MicrophoneMuted { get; private set; }
        public bool MicrophoneCaptureDisabled { get; private set; }
        public bool MicrophoneCapturing => microphone != null && microphone.IsCapturing;
        public bool MicrophoneTransmitting { get; private set; }
        public bool ReplyPlaying => replyAudio != null && replyAudio.IsPlaying;
        public long PlayedNonzeroSamples => replyAudio == null ? 0L : replyAudio.PlayedNonzeroSamples;
        public bool VoiceActionsAvailable { get; private set; }
        // Passive local observers share the existing control socket; they never acquire control.
        public event Action<string> BrainObservationReceived;
        public bool BrainConnected => bridgeConnected;
        public bool EnablingVoiceActions { get; private set; }
        public string BrainSessionId { get; private set; }
        public string BrainInstanceId { get; private set; }
        public string BridgeMotorHost { get; private set; }
        public int BridgeMotorPort { get; private set; }
        public string ActionFeedback { get; private set; } = "会話のみ。声で操作を有効にすると移動できます";
        public int SubmittedActions { get; private set; }
        public int AppliedActions { get; private set; }
        public int RejectedActions { get; private set; }
        public int LastAppliedRequestId { get; private set; }
        public string LastAppliedAction { get; private set; }
        public long LastAppliedSequence { get; private set; }
        public bool HasFreshBrain => bridgeConnected && !string.IsNullOrEmpty(BrainSessionId)
            && Time.realtimeSinceStartupAsDouble - frameReceivedAt <= .75
            && FrameAgeMs + (Time.realtimeSinceStartupAsDouble - stateReceivedAt) * 1000 <= 750;
        public bool BodyControlActive => bodyArmed && armedEpoch == ControlEpoch && Ready && ConversationLive
            && ConversationInteraction == "control" && Owner == "gpt" && !OutputInhibited && voiceControlAvailable && HasFreshBrain;

        void Awake()
        {
            MicrophoneCaptureDisabled = Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationNoMicrophone") >= 0;
            MicrophoneMuted = MicrophoneCaptureDisabled;
            if (FindAnyObjectByType<AudioListener>() == null)
            {
                // A filter cannot share an object with both listener and source.
                var listener = new GameObject("Conversation Audio Listener");
                listener.transform.SetParent(transform, false);
                listener.AddComponent<AudioListener>();
            }
            microphone = microphoneCapture ?? GetComponent<UnityMicrophoneCapture>() ?? gameObject.AddComponent<UnityMicrophoneCapture>();
            replyAudio = replyAudioPlayer ?? GetComponent<UnityReplyAudioPlayer>() ?? gameObject.AddComponent<UnityReplyAudioPlayer>();
            BindMicrophone();
            if (GetComponent<NativeConversationBody>() == null) gameObject.AddComponent<NativeConversationBody>();
            if (GetComponent<NativeConversationReaction>() == null) gameObject.AddComponent<NativeConversationReaction>();
        }

        public void AttachAudioAdapters(UnityMicrophoneCapture microphoneAdapter, UnityReplyAudioPlayer replyAudioAdapter)
        {
            if (microphone != null) microphone.PcmChunk -= OnPcmChunk;
            microphone = microphoneAdapter;
            replyAudio = replyAudioAdapter;
            BindMicrophone();
        }

        void Update()
        {
            for (var i = 0; i < MaximumMessagesPerUpdate && mainThread.TryDequeue(out var action); i++)
            {
                Interlocked.Decrement(ref mainThreadCount);
                action();
            }
            if (autoStartPending && Ready && OutputInhibited && transport != null && transport.IsConnected)
                StartConversation();
            UpdateMicrophone();
            if (bodyArmed && !BodyControlActive) BodyFault("voice_control_stopped_or_stale");
        }

        public async Task ConnectAsync(string url)
        {
            CloseTransport();
            var endpoint = ResolveEndpoint(url);
            if (!BridgeConversationSocket.TryValidateLoopbackUrl(endpoint, out _, out var validationError))
            {
                SetError(validationError);
                return;
            }
            cancellation = new CancellationTokenSource();
            transport = new BridgeConversationSocket();
            var attempt = ++connectionAttempt;
            transport.Message += json => EnqueueMain(attempt, () => HandleMessage(json));
            transport.Faulted += code => EnqueueMain(attempt, () => Disconnected(code));
            transport.Closed += code => EnqueueMain(attempt, () => Disconnected(code));
            Status = "connecting";
            Error = null;
            try
            {
                await transport.ConnectAsync(endpoint, cancellation.Token);
                EnqueueMain(attempt, () => { if (transport != null) Status = "connected"; });
            }
            catch (OperationCanceledException) { EnqueueMain(attempt, () => Disconnected("control_cancelled")); }
            catch (ConversationTransportException ex) { EnqueueMain(attempt, () => Disconnected(ex.Code)); }
            catch (Exception) { EnqueueMain(attempt, () => Disconnected("control_connect_failed")); }
        }

        public void StartConversation()
        {
            if (EnablingVoiceActions) return;
            autoStartPending = false;
            if (requestedStart) return;
            if (transport == null || !transport.IsConnected || !Ready || !OutputInhibited)
            {
                SetError("conversation_start_not_safe");
                return;
            }
            requestedStart = true;
            Error = null;
            Send(new ConversationStart { type = "conversation_start", interaction = "chat_only", controlEpoch = ControlEpoch });
        }

        public void StopConversation()
        {
            if (enableActionsRoutine != null) StopCoroutine(enableActionsRoutine);
            enableActionsRoutine = null;
            EnablingVoiceActions = resumePending = bodyArmed = false;
            autoStartPending = false;
            requestedStart = false;
            ConversationLive = false;
            StopCapture();
            DiscardReply();
            if (transport != null && transport.IsConnected) Send(new ConversationStop { type = "conversation_stop" });
        }

        public void EmergencyStop()
        {
            StopConversation();
            if (transport != null && transport.IsConnected) Send(new EmergencyStopMessage { type = "emergency_stop" });
        }

        public void EnableVoiceActions()
        {
            if (!Ready || !VoiceActionsAvailable || EnablingVoiceActions || BodyControlActive) return;
            int previousGeneration = ConversationGeneration;
            StopConversation();
            EnablingVoiceActions = true;
            Error = null;
            ActionFeedback = "声で操作の準備中：会話を切り替えています";
            enableActionsRoutine = StartCoroutine(EnableActions(previousGeneration));
        }

        IEnumerator EnableActions(int previousGeneration)
        {
            double deadline = Time.realtimeSinceStartupAsDouble + 25;
            while (Ready && Time.realtimeSinceStartupAsDouble < deadline
                && (ConversationGeneration <= previousGeneration || conversationStopping
                    || (bridgeConversationState != "off" && bridgeConversationState != "disconnected"))) yield return null;
            if (!Ready || conversationStopping || ConversationGeneration <= previousGeneration
                || (bridgeConversationState != "off" && bridgeConversationState != "disconnected"))
            { FailActionStart("voice_control_stop_timeout"); yield break; }
            requestedStart = true;
            Send(new ConversationStart { type = "conversation_start", interaction = "control", nativeVoiceControl = true, controlEpoch = ControlEpoch });
            ActionFeedback = "声で操作の準備中：実Brainの停止確認を待っています";
            deadline = Time.realtimeSinceStartupAsDouble + 30;
            while (Ready && Time.realtimeSinceStartupAsDouble < deadline
                && !(ConversationLive && resumeReady && voiceControlAvailable && HasFreshBrain && Owner == "gpt")) yield return null;
            if (!Ready || !ConversationLive || !resumeReady || !voiceControlAvailable || !HasFreshBrain || Owner != "gpt")
            { FailActionStart("fresh_stop_or_voice_required"); yield break; }
            armedEpoch = ControlEpoch;
            resumePending = true;
            Send(new ResumeMessage { type = "resume", controlEpoch = ControlEpoch });
            deadline = Time.realtimeSinceStartupAsDouble + 3;
            while (Ready && resumePending && Time.realtimeSinceStartupAsDouble < deadline) yield return null;
            if (!bodyArmed) { FailActionStart("voice_control_resume_failed"); yield break; }
            EnablingVoiceActions = false;
            enableActionsRoutine = null;
            ActionFeedback = "声で操作できます：前へ、右、左、止まって";
        }

        void FailActionStart(string code)
        {
            enableActionsRoutine = null;
            EmergencyStop();
            ActionFeedback = "操作を開始できません：" + code;
            SetError(code);
        }

        public void BodyFault(string code)
        {
            Debug.Log("NATIVE_BODY_STOP " + code + " epoch=" + ControlEpoch + " sequence=" + Sequence
                + " frameAgeMs=" + ((Time.realtimeSinceStartupAsDouble - frameReceivedAt) * 1000).ToString("F1", CultureInfo.InvariantCulture)
                + " serverAgeMs=" + (FrameAgeMs + (Time.realtimeSinceStartupAsDouble - stateReceivedAt) * 1000).ToString("F1", CultureInfo.InvariantCulture)
                + " inhibited=" + OutputInhibited + " voice=" + voiceControlAvailable);
            bodyArmed = resumePending = false;
            ActionFeedback = "身体を停止しました。再開には「声で操作」が必要です：" + code;
            SetError(code);
            if (transport != null && transport.IsConnected) Send(new EmergencyStopMessage { type = "emergency_stop" });
        }

        // The same intent route as voice delegation, useful for accessible input and explicit verification.
        public void SendPlayerText(string text)
        {
            if (!BodyControlActive || string.IsNullOrWhiteSpace(text) || text.Length > 2000) return;
            Send(new PlayerTextMessage { type = "player_text", text = text, controlEpoch = ControlEpoch,
                commandId = "unity-intent-" + Guid.NewGuid().ToString("N") });
        }

        public void ApplySettings(string language, string voice, string persona, string personaText)
        {
            if (ConversationLive || !OutputInhibited || transport == null || !transport.IsConnected)
            {
                SetError("conversation_settings_require_stopped");
                return;
            }
            expectedSettingsRequestId = "unity-settings-" + (++requestNumber).ToString(CultureInfo.InvariantCulture);
            Send(new ConfigureConversation {
                type = "configure_conversation", requestId = expectedSettingsRequestId,
                controlEpoch = ControlEpoch, expectedRevision = SettingsRevision,
                settings = new ConversationSettings { language = language, voice = voice, persona = persona, personaText = personaText }
            });
        }

        public void SetMicrophoneDevice(string device)
        {
            if (selectedDevice == device) return;
            selectedDevice = device;
            StopCapture();
        }

        public void SetMicrophoneMuted(bool muted)
        {
            muted |= MicrophoneCaptureDisabled;
            if (MicrophoneMuted == muted) return;
            MicrophoneMuted = muted;
            StopCapture();
        }

        public void SetVolume(float value)
        {
            if (replyAudio == null) return;
            replyAudio.Volume = Mathf.Clamp01(value);
        }

        void HandleMessage(string json)
        {
            try { HandleMessageCore(json); }
            catch (ArgumentException) { Disconnected("control_protocol_invalid"); }
        }

        void HandleMessageCore(string json)
        {
            MessageHeader header;
            try { header = JsonUtility.FromJson<MessageHeader>(json); }
            catch (ArgumentException) { Disconnected("control_protocol_invalid"); return; }
            if (header == null || string.IsNullOrEmpty(header.type)) { Disconnected("control_protocol_invalid"); return; }
            switch (header.type)
            {
                case "bridge_state": HandleBridgeState(JsonUtility.FromJson<BridgeState>(json)); break;
                case "conversation_options": Options = JsonUtility.FromJson<ConversationOptions>(json) ?? Options; break;
                case "conversation_settings": HandleSettings(JsonUtility.FromJson<ConversationSettingsMessage>(json)); break;
                case "conversation_state": HandleConversationState(JsonUtility.FromJson<ConversationStateMessage>(json)); break;
                case "conversation_text": HandleText(JsonUtility.FromJson<ConversationTextMessage>(json)); break;
                case "audio": HandleAudio(JsonUtility.FromJson<AudioMessage>(json)); break;
                case "discard_audio": HandleDiscard(JsonUtility.FromJson<GenerationMessage>(json)); break;
                case "error": HandleError(JsonUtility.FromJson<ErrorMessage>(json)); break;
                case "brain_frame": HandleFrame(JsonUtility.FromJson<BrainFrameMessage>(json)); break;
                case "command_result": HandleCommandResult(JsonUtility.FromJson<CommandResult>(json)); break;
            }
            if (header.type == "bridge_state" || header.type == "brain_frame")
                BrainObservationReceived?.Invoke(json);
        }

        void HandleBridgeState(BridgeState state)
        {
            if (state == null) return;
            if (state.epoch < ControlEpoch) return;
            bool boundary = state.epoch != ControlEpoch || state.sessionId != BrainSessionId || state.instanceId != BrainInstanceId;
            if (boundary)
            {
                frameReceivedAt = double.NegativeInfinity;
                Sequence = -1;
                pendingActions.Clear();
                LastAppliedRequestId = 0;
                LastAppliedSequence = 0;
            }
            ControlEpoch = state.epoch;
            Owner = string.IsNullOrEmpty(state.owner) ? "observer" : state.owner;
            OutputInhibited = state.outputInhibited;
            ConversationInteraction = string.IsNullOrEmpty(state.conversationInteraction) ? "chat_only" : state.conversationInteraction;
            Ready = HasCapability(state.capabilities, "conversation_only_v1");
            if (Ready) Status = "connected";
            Backend = state.backend;
            BrainReady = state.brainReady;
            FrameAgeMs = state.frameAgeMs;
            stateReceivedAt = Time.realtimeSinceStartupAsDouble;
            BrainSessionId = state.sessionId;
            BrainInstanceId = state.instanceId;
            bridgeConnected = state.brainConnected && !state.switching && !state.releaseUnknown;
            resumeReady = state.resumeReady;
            voiceControlAvailable = state.voiceControlAvailable;
            bridgeConversationState = state.conversationState;
            conversationStopping = state.conversationStopping;
            VoiceActionsAvailable = HasCapability(state.capabilities, "native_voice_actions_v1");
            if (state.motorEndpoint != null && (state.motorEndpoint.host == "127.0.0.1" || state.motorEndpoint.host == "localhost")
                && state.motorEndpoint.port > 0 && state.motorEndpoint.port <= 65535)
            { BridgeMotorHost = state.motorEndpoint.host; BridgeMotorPort = state.motorEndpoint.port; }
            if (state.conversationGeneration >= 0 && state.conversationGeneration != ConversationGeneration)
                ResetGeneration(state.conversationGeneration);
            if (state.conversationSettings != null) Settings = state.conversationSettings;
            SettingsRevision = state.conversationSettingsRevision;
            if (resumePending && ControlEpoch == armedEpoch && !OutputInhibited && HasFreshBrain && voiceControlAvailable)
            { bodyArmed = true; resumePending = false; }
        }

        void HandleConversationState(ConversationStateMessage state)
        {
            if (state == null || !AcceptGeneration(state.conversationGeneration)) return;
            ConversationLive = requestedStart && state.state == "live";
            if (!ConversationLive) StopCapture();
        }

        void HandleText(ConversationTextMessage text)
        {
            if (!requestedStart || text == null || !AcceptGeneration(text.conversationGeneration)) return;
            var incoming = text.text ?? string.Empty;
            if (!string.IsNullOrEmpty(text.role) && text.role != captionRole)
            {
                if (!string.IsNullOrEmpty(Caption)) Caption += "\n";
                Caption += text.role + ": ";
                captionRole = text.role;
            }
            Caption += incoming;
            if (Caption.Length > 4000) Caption = Caption.Substring(Caption.Length - 4000);
            ReceivedTranscriptDeltas++;
        }

        void HandleAudio(AudioMessage audio)
        {
            if (!requestedStart || audio == null || !AcceptGeneration(audio.conversationGeneration)) return;
            try
            {
                var bytes = Convert.FromBase64String(audio.audio ?? string.Empty);
                ReceivedAudioBytes += bytes.Length;
                foreach (byte value in bytes) if (value != 0) { ReceivedNonzeroAudioBytes += bytes.Length; break; }
                // Receiving a reply must never depend on microphone input being enabled.
                if (bytes.Length == 0) return;
                replyAudio?.EnqueuePcm(bytes);
            }
            catch (FormatException) { SetError("invalid_reply_audio"); }
        }

        void HandleDiscard(GenerationMessage discard)
        {
            if (!requestedStart || discard == null || !AcceptGeneration(discard.conversationGeneration)) return;
            DiscardReply();
        }

        void HandleSettings(ConversationSettingsMessage settings)
        {
            if (settings == null || settings.requestId != expectedSettingsRequestId) return;
            Settings = settings.settings ?? Settings;
            SettingsRevision = settings.revision;
            LastSettingsResult = "applied";
            expectedSettingsRequestId = null;
        }

        void HandleError(ErrorMessage error)
        {
            if (error == null) return;
            if (!string.IsNullOrEmpty(error.requestId) && error.requestId == expectedSettingsRequestId) expectedSettingsRequestId = null;
            string code = string.IsNullOrEmpty(error.error) ? "control_error" : error.error;
            if (code.IndexOf("schema", StringComparison.OrdinalIgnoreCase) >= 0) SchemaError = code;
            SetError(code);
        }

        bool AcceptGeneration(int incoming)
        {
            return incoming >= 0 && incoming == ConversationGeneration;
        }

        void ResetGeneration(int next)
        {
            ConversationGeneration = next;
            Caption = string.Empty;
            captionRole = null;
            ConversationLive = false;
            bodyArmed = false;
            StopCapture();
            DiscardReply();
        }

        void UpdateMicrophone()
        {
            bool active = CanTransmit();
            if (!active)
            {
                if (captureAttempted) StopCapture();
                return;
            }
            // Open once per session/device/unmute, including while the greeting plays.
            // GPT Live receives input continuously, including while reply audio plays.
            if (!captureAttempted) { captureAttempted = true; StartCapture(); }
            MicrophoneTransmitting = MicrophoneCapturing && CanTransmit();
            microphone?.SetTransmitting(MicrophoneTransmitting);
        }

        bool CanTransmit()
        {
            return !MicrophoneMuted && requestedStart && ConversationLive && Ready
                && ((OutputInhibited && Owner == "observer" && ConversationInteraction == "chat_only")
                    || (ConversationInteraction == "control" && Owner == "gpt"));
        }

        void StartCapture()
        {
            var devices = Devices;
            if (devices != null && devices.Length > 0)
            {
                if (string.IsNullOrEmpty(selectedDevice)) selectedDevice = devices[0];
                microphone.StartCapture(selectedDevice);
            }
        }
        void StopCapture() { MicrophoneTransmitting = false; microphone?.StopCapture(); captureAttempted = false; }
        void DiscardReply() { replyAudio?.Discard(); }

        void BindMicrophone()
        {
            if (microphone != null) microphone.PcmChunk += OnPcmChunk;
        }
        void OnPcmChunk(byte[] pcm)
        {
            if (!MicrophoneTransmitting || !CanTransmit() || pcm == null || pcm.Length == 0) return;
            SentAudioChunks++;
            if (ReplyPlaying) SentAudioChunksDuringReply++;
            Send(new AudioOutbound { type = "audio", conversationGeneration = ConversationGeneration, controlEpoch = ControlEpoch, audio = Convert.ToBase64String(pcm) });
        }

        void Send(object message)
        {
            try { transport.Enqueue(JsonUtility.ToJson(message)); }
            catch (ConversationTransportException ex) { Disconnected(ex.Code); }
        }
        void Disconnected(string code)
        {
            Status = "disconnected"; Ready = false; requestedStart = false; ConversationLive = false;
            autoStartPending = false;
            bodyArmed = resumePending = false;
            if (enableActionsRoutine != null) StopCoroutine(enableActionsRoutine);
            enableActionsRoutine = null;
            EnablingVoiceActions = false;
            StopCapture(); DiscardReply(); SetError(code); CloseTransport();
        }
        void EnqueueMain(int attempt, Action action)
        {
            if (attempt != connectionAttempt) return;
            if (Interlocked.Increment(ref mainThreadCount) > MaximumMainThreadMessages)
            {
                Interlocked.Decrement(ref mainThreadCount);
                transport?.Dispose();
                mainThread.Enqueue(() => Disconnected("control_mainthread_queue_full"));
                return;
            }
            mainThread.Enqueue(() => { if (attempt == connectionAttempt) action(); });
        }
        void CloseTransport()
        {
            connectionAttempt++;
            transport?.Dispose(); transport = null;
            cancellation?.Cancel(); cancellation?.Dispose(); cancellation = null;
        }
        void SetError(string code) { Error = code; }
        void OnDisable() { StopConversation(); CloseTransport(); }
        void OnDestroy()
        {
            StopConversation();
            if (microphone != null) microphone.PcmChunk -= OnPcmChunk;
            CloseTransport();
        }

        static string ResolveEndpoint(string supplied)
        {
            if (!string.IsNullOrEmpty(supplied)) return supplied;
            var args = Environment.GetCommandLineArgs();
            for (var i = 0; i + 1 < args.Length; i++) if (args[i] == "-flyBridgeControlUrl") return args[i + 1];
            return DefaultUrl;
        }
        static bool HasCapability(string[] values, string expected)
        {
            if (values == null) return false;
            foreach (var value in values) if (value == expected) return true;
            return false;
        }
        [Serializable] public sealed class ConversationSettings { public string language = "ja"; public string voice = "marin"; public string persona = "friendly"; public string personaText = ""; }
        [Serializable] sealed class MessageHeader { public string type; }
        [Serializable] sealed class BridgeState { public int epoch; public string owner; public bool outputInhibited; public string[] capabilities; public string conversationInteraction; public int conversationGeneration = -1; public ConversationSettings conversationSettings; public int conversationSettingsRevision; public string backend; public bool brainReady; public float frameAgeMs; public string sessionId, instanceId, conversationState; public bool brainConnected, resumeReady, voiceControlAvailable, conversationStopping, switching, releaseUnknown; public MotorEndpoint motorEndpoint; }
        [Serializable] sealed class MotorEndpoint { public string host; public int port; }
        void HandleFrame(BrainFrameMessage frame)
        {
            if (frame == null || frame.metadata == null || frame.motor == null || !bridgeConnected
                || frame.metadata.sessionId != BrainSessionId || frame.metadata.instanceId != BrainInstanceId
                || frame.sequence <= Sequence || float.IsNaN(frame.motor.forward) || float.IsInfinity(frame.motor.forward)
                || float.IsNaN(frame.motor.turn) || float.IsInfinity(frame.motor.turn)) return;
            Sequence = frame.sequence;
            frameReceivedAt = Time.realtimeSinceStartupAsDouble;
            // A state age describes the preceding frame. Only a NEW valid frame
            // starts a new age baseline; heartbeats/duplicates cannot refresh it.
            FrameAgeMs = 0;
            stateReceivedAt = frameReceivedAt;
            if (frame.appliedRequestId > 0 && frame.appliedRequestId == LastAppliedRequestId) LastAppliedSequence = frame.sequence;
        }
        void HandleCommandResult(CommandResult result)
        {
            if (result == null || ConversationInteraction != "control" || !requestedStart) return;
            if (result.stage == "submitted" && result.epoch == ControlEpoch && result.commandId != null
                && (result.commandId.StartsWith("voice-", StringComparison.Ordinal) || result.commandId.StartsWith("unity-intent-", StringComparison.Ordinal)))
            {
                if (pendingActions.Count >= 32) pendingActions.Clear();
                pendingActions[result.requestId] = result.action;
                SubmittedActions++;
                ActionFeedback = "指示を受付：" + result.action + "（Brain適用待ち）";
            }
            else if (result.stage == "brain_applied" && pendingActions.TryGetValue(result.requestId, out string action))
            {
                pendingActions.Remove(result.requestId);
                AppliedActions++;
                LastAppliedRequestId = result.requestId;
                LastAppliedAction = action;
                ActionFeedback = "Brainが適用：" + action + "（移動結果は身体観測で確認）";
            }
            else if (result.stage == "rejected") { RejectedActions++; ActionFeedback = "指示を実行できません：" + result.reason; }
        }

        [Serializable] sealed class ConversationStateMessage { public string state; public int conversationGeneration = -1; }
        [Serializable] class GenerationMessage { public int conversationGeneration = -1; }
        [Serializable] sealed class ConversationTextMessage : GenerationMessage { public string text; public string role; public bool append; }
        [Serializable] sealed class AudioMessage : GenerationMessage { public string audio; }
        [Serializable] sealed class ErrorMessage { public string error; public string requestId; }
        [Serializable] sealed class ConversationSettingsMessage { public string requestId; public ConversationSettings settings; public int revision; }
        [Serializable] sealed class ConversationStart { public string type; public string interaction; public int controlEpoch; public bool nativeVoiceControl; }
        [Serializable] sealed class ResumeMessage { public string type; public int controlEpoch; }
        [Serializable] sealed class PlayerTextMessage { public string type, text, commandId; public int controlEpoch; }
        [Serializable] sealed class CommandResult { public string stage, commandId, action, reason; public int epoch, requestId; }
        [Serializable] sealed class ConversationStop { public string type; }
        [Serializable] sealed class EmergencyStopMessage { public string type; }
        [Serializable] sealed class AudioOutbound { public string type; public int conversationGeneration, controlEpoch; public string audio; }
        [Serializable] sealed class ConfigureConversation { public string type; public string requestId; public int controlEpoch; public int expectedRevision; public ConversationSettings settings; }
        [Serializable] public sealed class ConversationOptions { public string[] languages; public string[] voices; public string[] personas; public int maxPersonaTextLength; }
        [Serializable] sealed class BrainFrameMessage { public long sequence; public int appliedRequestId; public FlyBrainPoC.BackendMetadata metadata; public FlyBrainPoC.MotorOutput motor; }
    }
}
