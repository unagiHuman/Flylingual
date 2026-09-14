using Flylingual.PlayScreen;
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
    /// Unity voice endpoint. Startup voice control uses the Bridge's fresh STOP/resume gate.
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
        int neuralSubscribedEpoch = -1, neuralSubscribedGeneration = -1;
        public bool NeuralResponseAvailable { get; private set; }
        public NeuralResponsePanel.Observation NeuralResponse { get; private set; }
        public double NeuralResponseReceivedAt { get; private set; } = double.NegativeInfinity;
        bool requestedStart;
        bool autoStartPending = true;
        bool startChatOnly;
        bool keepVoiceControl, applicationQuitting;
        string lastControlEndpoint;
        double nextRecoveryAt, nextMicrophoneRetryAt;
        bool captureAttempted;
        bool fixtureInputEnabled;
        string expectedSettingsRequestId;
        string startupLanguageAttempt;
        bool startupLanguageAcknowledged;
        double settingsRequestedAt;
        public bool SelectedLanguageReady => Settings.language == GameLanguage.Code
            && expectedSettingsRequestId == null && (startupLanguageAttempt == null || startupLanguageAcknowledged);
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
        public ExecutionObservation ActiveExecution { get; private set; }
        [Serializable] public sealed class ExecutionObservation
        {
            public string executionId, action, plan, executionMode, distancePhase;
            public int step;
            public float targetDistanceMeters, traveledMeters, remainingMeters;
        }
        public bool OutputInhibited { get; private set; } = true;
        public bool ConversationLive { get; private set; }
        public bool TextConversation { get; private set; }
        public bool ConversationActive => ConversationLive || TextConversation;
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
        /// <summary>True when this process was explicitly launched for synthetic fixture input.</summary>
        public bool FixtureInputEnabled => fixtureInputEnabled;
        /// <summary>The sole selected input path. Fixture mode never opens a physical microphone.</summary>
        public string InputSource => fixtureInputEnabled ? "synthetic_fixture" : "microphone";
        /// <summary>Whether a fixture chunk may currently be sent through the live conversation.</summary>
        public bool FixtureInputTransmitting => fixtureInputEnabled && CanTransmit();
        public long SentFixtureAudioChunks { get; private set; }
        public bool MicrophoneMuted { get; private set; }
        public bool MicrophoneCaptureDisabled { get; private set; }
        public bool MicrophoneCapturing => microphone != null && microphone.IsCapturing;
        public bool MicrophoneTransmitting { get; private set; }
        public bool ReplyPlaying => replyAudio != null && replyAudio.IsPlaying;
        public long PlayedNonzeroSamples => replyAudio == null ? 0L : replyAudio.PlayedNonzeroSamples;
        public bool VoiceActionsAvailable { get; private set; }
        public bool BlindRunScriptAvailable { get; private set; }
        public bool LocalVisualAvailable { get; private set; }
        long localVisualSequence;
        // Raw messages are exposed only to passive local observers of this existing control socket.
        public event Action<string> ControlEventReceived;
        // Passive local observers share the existing control socket; they never acquire control.
        public event Action<string> BrainObservationReceived;
        public bool BrainConnected => bridgeConnected;
        public bool EnablingVoiceActions { get; private set; }
        public bool ContinuousVoiceControl => keepVoiceControl;
        public string BrainSessionId { get; private set; }
        public string BrainInstanceId { get; private set; }
        public string BridgeMotorHost { get; private set; }
        public int BridgeMotorPort { get; private set; }
        public string ActionFeedback { get; private set; } = string.Empty;
        public int SubmittedActions { get; private set; }
        public int AppliedActions { get; private set; }
        public int RejectedActions { get; private set; }
        public int LastAppliedRequestId { get; private set; }
        public string LastAppliedAction { get; private set; }
        public long LastAppliedSequence { get; private set; }
        public bool HasFreshBrain => bridgeConnected && !string.IsNullOrEmpty(BrainSessionId)
            && Time.realtimeSinceStartupAsDouble - frameReceivedAt <= .75
            && FrameAgeMs + (Time.realtimeSinceStartupAsDouble - stateReceivedAt) * 1000 <= 750;
        public bool BodyControlActive => bodyArmed && armedEpoch == ControlEpoch && Ready && ConversationActive
            && ConversationInteraction == "control" && Owner == "gpt" && !OutputInhibited && voiceControlAvailable && HasFreshBrain;

        void Awake()
        {
            ActionFeedback = GameLanguage.Text("接続後に音声操作を開始します", "Voice controls will start after connecting");
            var commandLine = Environment.GetCommandLineArgs();
            startChatOnly = Array.IndexOf(commandLine, "-flyConversationChatOnly") >= 0;
            if (startChatOnly) ActionFeedback = GameLanguage.Text("会話のみ。身体操作は停止しています", "Chat only. Body controls are stopped");
            // The switch itself selects fixture input. A missing or invalid manifest must not
            // silently turn on physical capture.
            fixtureInputEnabled = Array.IndexOf(commandLine, "-flyVoiceFixtures") >= 0;
            MicrophoneCaptureDisabled = Array.IndexOf(commandLine, "-flyConversationNoMicrophone") >= 0;
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
            if (keepVoiceControl && Ready && Time.realtimeSinceStartupAsDouble - stateReceivedAt > 3)
                Disconnected("control_state_timeout");
            PrepareSelectedLanguage();
            if (!TitleScreen.BlocksGameplay && autoStartPending && SelectedLanguageReady && Ready && OutputInhibited && transport != null && transport.IsConnected)
            {
                // The bootstrap starts once; continuous control owns subsequent recovery.
                if (startChatOnly) StartConversation();
                else if (VoiceActionsAvailable) EnableVoiceActions();
            }
            UpdateMicrophone();
            if (bodyArmed && !BodyControlActive) BodyFault("voice_control_stopped_or_stale");
            MaintainVoiceControl();
        }

        void PrepareSelectedLanguage()
        {
            if (expectedSettingsRequestId != null && Time.realtimeSinceStartupAsDouble - settingsRequestedAt > 10)
            {
                expectedSettingsRequestId = null;
                LastSettingsResult = "timeout";
                SetError("conversation_settings_timeout");
            }
            if (!autoStartPending || !Ready || ConversationActive || conversationStopping || !OutputInhibited
                || transport == null || !transport.IsConnected || expectedSettingsRequestId != null
                || Settings.language == GameLanguage.Code || startupLanguageAttempt == GameLanguage.Code) return;
            // One request per selected language. Wait for its matching acknowledgement before starting.
            // Failure remains stopped; the settings UI can explicitly retry without a request loop.
            startupLanguageAttempt = GameLanguage.Code;
            startupLanguageAcknowledged = false;
            ApplySettings(GameLanguage.Code, Settings.voice, Settings.persona, Settings.personaText);
        }

        void MaintainVoiceControl()
        {
            if (TitleScreen.BlocksGameplay) return;
            if (!keepVoiceControl || applicationQuitting || Time.realtimeSinceStartupAsDouble < nextRecoveryAt) return;
            if (transport == null && !string.IsNullOrEmpty(lastControlEndpoint))
            {
                nextRecoveryAt = Time.realtimeSinceStartupAsDouble + 5;
                _ = ConnectAsync(lastControlEndpoint);
                return;
            }
            if (!Ready || !VoiceActionsAvailable || !HasFreshBrain || BodyControlActive || EnablingVoiceActions) return;
            nextRecoveryAt = Time.realtimeSinceStartupAsDouble + 5;
            // Recovery always starts a fresh voice epoch through STOP/resume.
            // No old text, audio, or movement request is queued for replay.
            EnableVoiceActions();
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
            cancellation.CancelAfter(TimeSpan.FromSeconds(10));
            lastControlEndpoint = endpoint;
            ControlEpoch = 0;
            Ready = bridgeConnected = bodyArmed = resumePending = false;
            frameReceivedAt = double.NegativeInfinity;
            BrainSessionId = BrainInstanceId = null;
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
                if (attempt == connectionAttempt) cancellation.CancelAfter(Timeout.InfiniteTimeSpan);
                EnqueueMain(attempt, () => { if (transport != null) Status = "connected"; });
            }
            catch (OperationCanceledException) { EnqueueMain(attempt, () => Disconnected("control_cancelled")); }
            catch (ConversationTransportException ex) { EnqueueMain(attempt, () => Disconnected(ex.Code)); }
            catch (Exception) { EnqueueMain(attempt, () => Disconnected("control_connect_failed")); }
        }

        public void StartConversation()
        {
            if (EnablingVoiceActions || !SelectedLanguageReady) return;
            keepVoiceControl = false;
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
            keepVoiceControl = false;
            if (enableActionsRoutine != null) StopCoroutine(enableActionsRoutine);
            enableActionsRoutine = null;
            EnablingVoiceActions = resumePending = bodyArmed = false;
            autoStartPending = false;
            requestedStart = false;
            ConversationLive = false; TextConversation = false;
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
            if (!SelectedLanguageReady || !Ready || !VoiceActionsAvailable || EnablingVoiceActions || BodyControlActive) return;
            int previousGeneration = ConversationGeneration;
            StopConversation();
            keepVoiceControl = true;
            EnablingVoiceActions = true;
            Error = null;
            ActionFeedback = GameLanguage.Text("声で操作の準備中：会話を切り替えています", "Preparing voice controls: switching conversation");
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
            ActionFeedback = GameLanguage.Text("声で操作の準備中：実Brainの停止確認を待っています", "Preparing voice controls: waiting for Brain to confirm STOP");
            deadline = Time.realtimeSinceStartupAsDouble + 30;
            while (Ready && Time.realtimeSinceStartupAsDouble < deadline
                && !(ConversationActive && resumeReady && voiceControlAvailable && HasFreshBrain && Owner == "gpt")) yield return null;
            if (!Ready || !ConversationActive || !resumeReady || !voiceControlAvailable || !HasFreshBrain || Owner != "gpt")
            { FailActionStart("fresh_stop_or_voice_required"); yield break; }
            armedEpoch = ControlEpoch;
            resumePending = true;
            Send(new ResumeMessage { type = "resume", controlEpoch = ControlEpoch });
            deadline = Time.realtimeSinceStartupAsDouble + 3;
            while (Ready && resumePending && Time.realtimeSinceStartupAsDouble < deadline) yield return null;
            if (!bodyArmed) { FailActionStart("voice_control_resume_failed"); yield break; }
            EnablingVoiceActions = false;
            enableActionsRoutine = null;
            ActionFeedback = GameLanguage.Text("声で操作できます：前へ、右、左、止まって", "Voice controls ready: forward, right, left, stop");
        }

        void FailActionStart(string code)
        {
            bool retry = keepVoiceControl;
            enableActionsRoutine = null;
            EmergencyStop();
            keepVoiceControl = retry;
            nextRecoveryAt = Time.realtimeSinceStartupAsDouble + 5;
            ActionFeedback = retry ? GameLanguage.Text("音声操作への接続を再試行します：", "Retrying voice controls: ") + code : GameLanguage.Text("操作を開始できません：", "Unable to start controls: ") + code;
            SetError(code);
        }

        public void BodyFault(string code)
        {
            Debug.Log("NATIVE_BODY_STOP " + code + " epoch=" + ControlEpoch + " sequence=" + Sequence
                + " frameAgeMs=" + ((Time.realtimeSinceStartupAsDouble - frameReceivedAt) * 1000).ToString("F1", CultureInfo.InvariantCulture)
                + " serverAgeMs=" + (FrameAgeMs + (Time.realtimeSinceStartupAsDouble - stateReceivedAt) * 1000).ToString("F1", CultureInfo.InvariantCulture)
                + " inhibited=" + OutputInhibited + " voice=" + voiceControlAvailable);
            bodyArmed = resumePending = false;
            nextRecoveryAt = Time.realtimeSinceStartupAsDouble + 2;
            ActionFeedback = keepVoiceControl ? GameLanguage.Text("身体を停止し、音声操作への接続を復旧しています：", "Body stopped; reconnecting voice controls: ") + code
                : GameLanguage.Text("身体を停止しました：", "Body stopped: ") + code;
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
            if (!Ready || ConversationActive || conversationStopping || !OutputInhibited || expectedSettingsRequestId != null || transport == null || !transport.IsConnected)
            {
                SetError("conversation_settings_require_stopped");
                return;
            }
            settingsRequestedAt = Time.realtimeSinceStartupAsDouble;
            LastSettingsResult = "pending";
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

        /// <summary>Enables Bridge-side fixture timing diagnostics on the existing control socket.</summary>
        public bool EnableVoiceTestObservation()
        {
            if (!fixtureInputEnabled || !Ready || transport == null || !transport.IsConnected) return false;
            Send(new VoiceTestObservation { type = "voice_test_observation", enabled = true });
            return true;
        }

        public void SetVolume(float value)
        {
            if (replyAudio == null) return;
            replyAudio.Volume = Mathf.Clamp01(value);
        }

        void HandleMessage(string json)
        {
            try { ControlEventReceived?.Invoke(json); }
            catch (Exception exception) { Debug.LogWarning("Control event observer failed: " + exception.Message); }
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
                case "neural_response": HandleNeuralResponse(json); break;
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
                ResetNeuralResponse();
                frameReceivedAt = double.NegativeInfinity;
                Sequence = -1;
                pendingActions.Clear();
                LastAppliedRequestId = 0;
                LastAppliedSequence = 0;
            }
            ControlEpoch = state.epoch;
            Owner = string.IsNullOrEmpty(state.owner) ? "observer" : state.owner;
            OutputInhibited = state.outputInhibited;
            // JsonUtility creates an empty nested object for a JSON null.
            ActiveExecution = state.outputInhibited || state.activeExecution == null
                || string.IsNullOrEmpty(state.activeExecution.executionId) ? null : state.activeExecution;
            ConversationInteraction = string.IsNullOrEmpty(state.conversationInteraction) ? "chat_only" : state.conversationInteraction;
            Ready = HasCapability(state.capabilities, "conversation_only_v1");
            BlindRunScriptAvailable = HasCapability(state.capabilities, "blind_run_script_v1");
            LocalVisualAvailable = HasCapability(state.capabilities, "local_visual_observation_v1");
            NeuralResponseAvailable = HasCapability(state.capabilities, "neural_response_v1");
            if (!NeuralResponseAvailable) ResetNeuralResponse();
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
            if (NeuralResponseAvailable && ConversationGeneration >= 0 &&
                (neuralSubscribedEpoch != ControlEpoch || neuralSubscribedGeneration != ConversationGeneration))
            {
                Send(new NeuralSubscribe { controlEpoch = ControlEpoch, conversationGeneration = ConversationGeneration });
                neuralSubscribedEpoch = ControlEpoch; neuralSubscribedGeneration = ConversationGeneration;
            }
        }

        void ResetNeuralResponse()
        {
            NeuralResponse = null; NeuralResponseReceivedAt = double.NegativeInfinity;
            neuralSubscribedEpoch = neuralSubscribedGeneration = -1;
        }

        void HandleNeuralResponse(string json)
        {
            if (!NeuralResponseAvailable || json.Length > 65536) return;
            // Optional diagnostics must never disconnect the control channel.
            try
            {
                var value = NeuralResponsePanel.Parse(json);
                if (value == null || value.schemaVersion != 1 || value.controlEpoch != ControlEpoch ||
                    value.conversationGeneration != ConversationGeneration || value.identity == null ||
                    value.identity.sessionId != BrainSessionId || value.identity.instanceId != BrainInstanceId) return;
                NeuralResponse = value; NeuralResponseReceivedAt = Time.realtimeSinceStartupAsDouble;
            }
            catch (ArgumentException) { }
        }

        [Serializable] sealed class NeuralSubscribe
        {
            public string type = "neural_observation_subscribe";
            public int controlEpoch, conversationGeneration;
            public bool enabled = true;
        }

        void HandleConversationState(ConversationStateMessage state)
        {
            if (state == null || !AcceptGeneration(state.conversationGeneration)) return;
            ConversationLive = requestedStart && state.state == "live";
            TextConversation = requestedStart && state.state == "text";
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
            startupLanguageAcknowledged = true;
            GameLanguage.SetLanguage(Settings.language);
        }

        void HandleError(ErrorMessage error)
        {
            if (error == null) return;
            if (error.error == "old_epoch" && error.hasEpochContext
                && error.submittedEpoch >= 0 && error.submittedEpoch < error.currentEpoch
                && (error.requestType == "local_safety_observation" || error.requestType == "blind_run_cue"
                    || error.requestType == "local_visual_observation"))
            {
                // Queued observations can cross a stop/retry boundary. The Bridge rejected them
                // correctly; do not latch a recovered-session UI error. Control failures stay visible.
                Debug.Log("Discarded stale observation: " + error.requestType + " epoch "
                    + error.submittedEpoch + " -> " + error.currentEpoch);
                return;
            }
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
            ResetNeuralResponse();
            ConversationGeneration = next;
            Caption = string.Empty;
            captionRole = null;
            ConversationLive = false; TextConversation = false;
            bodyArmed = false;
            StopCapture();
            DiscardReply();
        }

        void UpdateMicrophone()
        {
            if (fixtureInputEnabled)
            {
                // Fixture chunks are injected explicitly through TrySendFixturePcm. Do not
                // claim a microphone state or allow an adapter to begin physical capture.
                MicrophoneTransmitting = false;
                microphone?.SetTransmitting(false);
                if (MicrophoneCapturing) microphone.StopCapture();
                captureAttempted = false;
                return;
            }
            bool active = CanTransmit();
            if (!active)
            {
                if (captureAttempted) StopCapture();
                return;
            }
            // Open once per session/device/unmute, including while the greeting plays.
            // GPT Live receives input continuously, including while reply audio plays.
            if (captureAttempted && (!MicrophoneCapturing || !string.IsNullOrEmpty(microphone.Error)))
            {
                StopCapture();
                nextMicrophoneRetryAt = Time.realtimeSinceStartupAsDouble + 2;
            }
            if (!captureAttempted && Time.realtimeSinceStartupAsDouble >= nextMicrophoneRetryAt)
            { captureAttempted = true; StartCapture(); }
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
            if (!MicrophoneTransmitting) return;
            if (!TrySendPcm(pcm, ControlEpoch, ConversationGeneration)) return;
            SentAudioChunks++;
            if (ReplyPlaying) SentAudioChunksDuringReply++;
        }

        /// <summary>
        /// Sends one converted 24 kHz mono, 100 ms fixture chunk through the same outbound
        /// conversation path as microphone PCM. Stale generations and muted/live boundaries
        /// are rejected instead of replaying fixture audio across a control boundary.
        /// </summary>
        public bool TrySendFixturePcm(byte[] pcm, int expectedEpoch, int expectedGeneration,
            string fixtureId = null, int fixtureChunkIndex = -1)
        {
            if (!fixtureInputEnabled || !FixtureInputTransmitting) return false;
            if (!IsFixtureTagValid(fixtureId, fixtureChunkIndex)) return false;
            if (!TrySendPcm(pcm, expectedEpoch, expectedGeneration, fixtureId, fixtureChunkIndex)) return false;
            SentFixtureAudioChunks++;
            return true;
        }

        bool TrySendPcm(byte[] pcm, int expectedEpoch, int expectedGeneration,
            string fixtureId = null, int fixtureChunkIndex = -1)
        {
            if (!CanTransmit() || expectedEpoch != ControlEpoch || expectedGeneration != ConversationGeneration)
                return false;
            if (pcm == null || pcm.Length != PcmStreamConverter.ChunkSamples * sizeof(short)) return false;
            string audio = Convert.ToBase64String(pcm);
            if (fixtureId == null)
                Send(new AudioOutbound { type = "audio", conversationGeneration = ConversationGeneration, controlEpoch = ControlEpoch, audio = audio });
            else
                Send(new FixtureAudioOutbound
                {
                    type = "audio", conversationGeneration = ConversationGeneration, controlEpoch = ControlEpoch, audio = audio,
                    fixtureId = fixtureId, fixtureChunkIndex = fixtureChunkIndex,
                });
            return true;
        }

        static bool IsFixtureTagValid(string fixtureId, int fixtureChunkIndex)
        {
            if (fixtureId == null && fixtureChunkIndex == -1) return true; // untagged silence
            if (string.IsNullOrEmpty(fixtureId) || fixtureId.Length > 64 || fixtureChunkIndex < 0) return false;
            for (int i = 0; i < fixtureId.Length; i++)
            {
                char value = fixtureId[i];
                if (!((value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z')
                    || (value >= '0' && value <= '9') || value == '_' || value == '-')) return false;
            }
            return true;
        }

        // Stage observations only: does not acquire control or submit an Action.
        internal bool TrySendBlindRunCue(string runId, int attempt, long sequence, string cue, string evidenceJson, float ageMs)
        {
            if (!Ready || !BlindRunScriptAvailable || !ConversationActive || ConversationInteraction != "control"
                || !bridgeConnected || conversationStopping || (cue != "link_error" && !HasFreshBrain)
                || transport == null || !transport.IsConnected || ConversationGeneration < 0) return false;
            var envelope = new BlindRunEnvelope { controlEpoch = ControlEpoch, conversationGeneration = ConversationGeneration,
                runId = runId, attempt = attempt, sequence = sequence, cue = cue };
            string json = JsonUtility.ToJson(envelope);
            json = json.Substring(0, json.Length - 1) + ",\"ageMs\":__OBSERVATION_AGE__,\"evidence\":" + evidenceJson + "}";
            try { transport.EnqueueFresh(json, ageMs); return true; }
            catch (ConversationTransportException) { return false; }
        }
        [Serializable] sealed class BlindRunEnvelope
        {
            public string type = "blind_run_cue", runId, cue;
            public int controlEpoch, conversationGeneration, attempt;
            public long sequence;
        }

        // Read-only presentation data shares this socket; never acquire control or queue behind audio/actions.
        internal bool TrySendLocalVisualObservation(string factsJson, float ageMs)
        {
            if (!Ready || !LocalVisualAvailable || !ConversationActive || ConversationInteraction != "control"
                || conversationStopping || ConversationGeneration < 0 || transport == null || !transport.IsConnected
                || transport.QueueDepth >= 4 || string.IsNullOrEmpty(factsJson)
                || float.IsNaN(ageMs) || float.IsInfinity(ageMs) || ageMs < 0 || ageMs > 750) return false;
            var envelope = new LocalVisualEnvelope { controlEpoch = ControlEpoch,
                conversationGeneration = ConversationGeneration, sequence = ++localVisualSequence };
            string json = JsonUtility.ToJson(envelope);
            json = json.Substring(0, json.Length - 1) + ",\"ageMs\":__OBSERVATION_AGE__,\"facts\":" + factsJson + "}";
            try { transport.EnqueueFresh(json, ageMs); return true; }
            catch (ConversationTransportException) { return false; }
        }
        [Serializable] sealed class LocalVisualEnvelope
        {
            public string type = "local_visual_observation";
            public int controlEpoch, conversationGeneration;
            public long sequence;
        }

        public void SendLocalSafetyObservation(int sequence, float ageMs, bool groundPresent, string leftEdge, string rightEdge, bool forwardBlocked, bool bodyUnsafe, double travelMeters = -1, float horizontalSpeedMetersPerSecond = -1)
        {
            if (!Ready || ConversationInteraction != "control" || ConversationGeneration < 0 ||
                sequence <= 0 || float.IsNaN(ageMs) || ageMs < 0f || ageMs > 750f) return;
            Send(new LocalSafetyMessage { sequence = sequence, ageMs = ageMs, controlEpoch = ControlEpoch,
                conversationGeneration = ConversationGeneration, groundPresent = groundPresent,
                leftEdge = leftEdge, rightEdge = rightEdge, forwardBlocked = forwardBlocked, bodyUnsafe = bodyUnsafe,
                travelMeters = double.IsNaN(travelMeters) || double.IsInfinity(travelMeters) ? -1 : travelMeters,
                horizontalSpeedMetersPerSecond = float.IsNaN(horizontalSpeedMetersPerSecond) || float.IsInfinity(horizontalSpeedMetersPerSecond) ? -1 : horizontalSpeedMetersPerSecond });
        }

        public void SendBodyResponseObservation(int sequence, float horizontalSpeed, float forwardSpeed, float yawRate, double travel)
        {
            if (!NeuralResponseAvailable || !HasFreshBrain || transport == null || !transport.IsConnected ||
                transport.QueueDepth >= 4 || Sequence < 0 || string.IsNullOrEmpty(BrainInstanceId) ||
                float.IsNaN(horizontalSpeed) || float.IsInfinity(horizontalSpeed) || horizontalSpeed < 0 ||
                float.IsNaN(forwardSpeed) || float.IsInfinity(forwardSpeed) ||
                float.IsNaN(yawRate) || float.IsInfinity(yawRate) || double.IsNaN(travel) || double.IsInfinity(travel) || travel < 0) return;
            var observation = new BodyResponseObservation { sequence = sequence,
                controlEpoch = ControlEpoch, conversationGeneration = ConversationGeneration,
                brainSequence = Sequence, brainSessionId = BrainSessionId, brainInstanceId = BrainInstanceId,
                horizontalSpeedMetersPerSecond = horizontalSpeed, forwardSpeedMetersPerSecond = forwardSpeed,
                yawRateDegreesPerSecond = yawRate, travelMeters = travel,
                unityMonotonicMs = Time.realtimeSinceStartupAsDouble * 1000 };
            string json = JsonUtility.ToJson(observation);
            json = json.Substring(0, json.Length - 1) + ",\"ageMs\":__OBSERVATION_AGE__}";
            try { transport.EnqueueFresh(json, 0); }
            catch (ConversationTransportException) { } // Drop optional observations under pressure.
        }

        [Serializable] sealed class BodyResponseObservation
        {
            public string type = "body_response_observation";
            public int controlEpoch, conversationGeneration, sequence;
            public float horizontalSpeedMetersPerSecond, forwardSpeedMetersPerSecond, yawRateDegreesPerSecond;
            public long brainSequence;
            public string brainSessionId, brainInstanceId;
            public double travelMeters, unityMonotonicMs;
        }
        [Serializable] sealed class LocalSafetyMessage
        {
            public string type = "local_safety_observation";
            public int controlEpoch, conversationGeneration, sequence;
            public float ageMs;
            public double travelMeters = -1;
            public float horizontalSpeedMetersPerSecond = -1;
            public bool groundPresent, forwardBlocked, bodyUnsafe;
            public string leftEdge, rightEdge;
        }

        void Send(object message)
        {
            try { transport.Enqueue(JsonUtility.ToJson(message)); }
            catch (ConversationTransportException ex) { Disconnected(ex.Code); }
        }
        void Disconnected(string code)
        {
            NeuralResponseAvailable = false; ResetNeuralResponse();
            Status = "disconnected"; Ready = false; requestedStart = false; ConversationLive = false; TextConversation = false;
            ActiveExecution = null;
            autoStartPending = false;
            nextRecoveryAt = Time.realtimeSinceStartupAsDouble + 2;
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
        void OnApplicationQuit() { applicationQuitting = true; StopConversation(); }
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
        [Serializable] sealed class BridgeState { public int epoch; public string owner; public bool outputInhibited; public ExecutionObservation activeExecution; public string[] capabilities; public string conversationInteraction; public int conversationGeneration = -1; public ConversationSettings conversationSettings; public int conversationSettingsRevision; public string backend; public bool brainReady; public float frameAgeMs; public string sessionId, instanceId, conversationState; public bool brainConnected, resumeReady, voiceControlAvailable, conversationStopping, switching, releaseUnknown; public MotorEndpoint motorEndpoint; }
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
            if (result.stage == "execution_finished" && result.epoch == ControlEpoch)
            {
                ActionFeedback = result.reason == "distance_reached" ? GameLanguage.Text("指定距離の付近で停止。次の指示を待っています", "Stopped near the requested distance. Waiting for your next command")
                    : result.reason == "distance_stalled" ? GameLanguage.Text("進めないため停止。次の指示を待っています", "Stopped because movement stalled. Waiting for your next command")
                    : result.reason == "distance_overshoot" ? GameLanguage.Text("指定距離を越えて停止。次の指示を待っています", "Stopped past the requested distance. Waiting for your next command")
                    : result.reason == "distance_shortfall" ? GameLanguage.Text("指定距離の手前で停止。次の指示を待っています", "Stopped short of the requested distance. Waiting for your next command")
                    : GameLanguage.Text("距離移動を中断。次の指示を待っています", "Distance movement interrupted. Waiting for your next command");
                return;
            }
            if (result.stage == "submitted" && result.epoch == ControlEpoch && result.commandId != null
                && result.commandId.StartsWith("expired-stop-", StringComparison.Ordinal))
                ActionFeedback = GameLanguage.Text("行動時間が終了。次の音声指示を待っています", "Action time ended. Waiting for your next voice command");
            if (result.stage == "submitted" && result.epoch == ControlEpoch && result.commandId != null
                && (result.commandId.StartsWith("voice-", StringComparison.Ordinal) || result.commandId.StartsWith("unity-intent-", StringComparison.Ordinal)))
            {
                if (pendingActions.Count >= 32) pendingActions.Clear();
                pendingActions[result.requestId] = result.action;
                SubmittedActions++;
                ActionFeedback = GameLanguage.Text("指示を受付：", "Command accepted: ") + result.action + GameLanguage.Text("（Brain適用待ち）", " (waiting for Brain to apply)");
            }
            else if (result.stage == "brain_applied" && pendingActions.TryGetValue(result.requestId, out string action))
            {
                pendingActions.Remove(result.requestId);
                AppliedActions++;
                LastAppliedRequestId = result.requestId;
                LastAppliedAction = action;
                ActionFeedback = GameLanguage.Text("Brainが適用：", "Brain applied: ") + action + GameLanguage.Text("（移動結果は身体観測で確認）", " (movement is verified through body observations)");
            }
            else if (result.stage == "rejected") { RejectedActions++; ActionFeedback = GameLanguage.Text("指示を実行できません：", "Unable to execute command: ") + result.reason; }
        }

        [Serializable] sealed class ConversationStateMessage { public string state; public int conversationGeneration = -1; }
        [Serializable] class GenerationMessage { public int conversationGeneration = -1; }
        [Serializable] sealed class ConversationTextMessage : GenerationMessage { public string text; public string role; public bool append; }
        [Serializable] sealed class AudioMessage : GenerationMessage { public string audio; }
        [Serializable] sealed class ErrorMessage
        {
            public string error, requestId, requestType;
            public bool hasEpochContext;
            public int submittedEpoch, currentEpoch;
        }
        [Serializable] sealed class ConversationSettingsMessage { public string requestId; public ConversationSettings settings; public int revision; }
        [Serializable] sealed class ConversationStart { public string type; public string interaction; public int controlEpoch; public bool nativeVoiceControl; }
        [Serializable] sealed class ResumeMessage { public string type; public int controlEpoch; }
        [Serializable] sealed class PlayerTextMessage { public string type, text, commandId; public int controlEpoch; }
        [Serializable] sealed class CommandResult { public string stage, commandId, action, reason; public int epoch, requestId; }
        [Serializable] sealed class ConversationStop { public string type; }
        [Serializable] sealed class EmergencyStopMessage { public string type; }
        [Serializable] sealed class AudioOutbound { public string type; public int conversationGeneration, controlEpoch; public string audio; }
        [Serializable] sealed class FixtureAudioOutbound { public string type; public int conversationGeneration, controlEpoch; public string audio; public string fixtureId; public int fixtureChunkIndex; }
        [Serializable] sealed class VoiceTestObservation { public string type; public bool enabled; }
        [Serializable] sealed class ConfigureConversation { public string type; public string requestId; public int controlEpoch; public int expectedRevision; public ConversationSettings settings; }
        [Serializable] public sealed class ConversationOptions { public string[] languages; public string[] voices; public string[] personas; public int maxPersonaTextLength; }
        [Serializable] sealed class BrainFrameMessage { public long sequence; public int appliedRequestId; public FlyBrainPoC.BackendMetadata metadata; public FlyBrainPoC.MotorOutput motor; }
    }
}
