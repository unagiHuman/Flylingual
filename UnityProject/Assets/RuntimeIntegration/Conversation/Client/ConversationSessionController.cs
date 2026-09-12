using System;
using System.Collections.Concurrent;
using System.Globalization;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>
    /// Conversation-only Unity endpoint. This class never sends owner, resume, or action commands.
    /// A bootstrap must explicitly call ConnectAsync; Awake/Start deliberately do not connect.
    /// </summary>
    public sealed class ConversationSessionController : MonoBehaviour
    {
        const string DefaultUrl = "ws://127.0.0.1:18771/ws";
        const float ReplyTailSeconds = .2f;
        const int MaximumMainThreadMessages = 256;
        const int MaximumMessagesPerUpdate = 64;
        readonly ConcurrentQueue<Action> mainThread = new ConcurrentQueue<Action>();
        BridgeConversationSocket transport;
        CancellationTokenSource cancellation;
        UnityMicrophoneCapture microphone;
        UnityReplyAudioPlayer replyAudio;
        int requestNumber;
        bool requestedStart;
        bool pttHeld;
        float replyBlockedUntil;
        string expectedSettingsRequestId;
        string selectedDevice;
        string captionRole;
        int mainThreadCount;
        int connectionAttempt;

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

        void Awake()
        {
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
            if (replyAudio != null && replyAudio.IsPlaying) replyBlockedUntil = Time.unscaledTime + ReplyTailSeconds;
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
            if (transport == null || !transport.IsConnected || !Ready || !OutputInhibited)
            {
                SetError("conversation_start_not_safe");
                return;
            }
            requestedStart = true;
            Send(new ConversationStart { type = "conversation_start", interaction = "chat_only", controlEpoch = ControlEpoch });
        }

        public void StopConversation()
        {
            requestedStart = false;
            ConversationLive = false;
            SetPtt(false);
            StopCapture();
            DiscardReply();
            if (transport != null && transport.IsConnected) Send(new ConversationStop { type = "conversation_stop" });
        }

        public void EmergencyStop()
        {
            StopConversation();
            if (transport != null && transport.IsConnected) Send(new EmergencyStopMessage { type = "emergency_stop" });
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
            selectedDevice = device;
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
            }
        }

        void HandleBridgeState(BridgeState state)
        {
            if (state == null) return;
            ControlEpoch = state.epoch;
            Owner = string.IsNullOrEmpty(state.owner) ? "observer" : state.owner;
            OutputInhibited = state.outputInhibited;
            ConversationInteraction = string.IsNullOrEmpty(state.conversationInteraction) ? "chat_only" : state.conversationInteraction;
            Ready = HasCapability(state.capabilities, "conversation_only_v1");
            if (Ready) Status = "connected";
            Backend = state.backend;
            BrainReady = state.brainReady;
            FrameAgeMs = state.frameAgeMs;
            if (state.conversationGeneration >= 0 && state.conversationGeneration != ConversationGeneration)
                ResetGeneration(state.conversationGeneration);
            if (state.conversationSettings != null) Settings = state.conversationSettings;
            SettingsRevision = state.conversationSettingsRevision;
        }

        void HandleConversationState(ConversationStateMessage state)
        {
            if (state == null || !AcceptGeneration(state.conversationGeneration)) return;
            ConversationLive = requestedStart && state.state == "live";
            if (!ConversationLive) { SetPtt(false); StopCapture(); }
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
                if (bytes.Length == 0 || pttHeld) return;
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
            SetPtt(false);
            StopCapture();
            DiscardReply();
        }

        public void SetPushToTalk(bool held)
        {
            if (held && CanTransmit())
            {
                if (!pttHeld) { DiscardReply(false); StartCapture(); }
                SetPtt(true);
            }
            else SetPtt(false);
        }

        bool CanTransmit()
        {
            return requestedStart && ConversationLive && Ready && OutputInhibited && Owner == "observer"
                && ConversationInteraction == "chat_only"
                && (replyAudio == null || !replyAudio.IsPlaying) && Time.unscaledTime >= replyBlockedUntil;
        }

        void SetPtt(bool enabled)
        {
            pttHeld = enabled;
            microphone?.SetTransmitting(enabled && CanTransmit());
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
        void StopCapture() { microphone?.StopCapture(); }
        void DiscardReply(bool extendTail = true) { replyAudio?.Discard(); replyBlockedUntil = extendTail ? Time.unscaledTime + ReplyTailSeconds : 0f; }

        void BindMicrophone()
        {
            if (microphone != null) microphone.PcmChunk += OnPcmChunk;
        }
        void OnPcmChunk(byte[] pcm)
        {
            if (!CanTransmit() || pcm == null || pcm.Length == 0) return;
            SentAudioChunks++;
            Send(new AudioOutbound { type = "audio", conversationGeneration = ConversationGeneration, audio = Convert.ToBase64String(pcm) });
        }

        void Send(object message)
        {
            try { transport.Enqueue(JsonUtility.ToJson(message)); }
            catch (ConversationTransportException ex) { Disconnected(ex.Code); }
        }
        void Disconnected(string code)
        {
            Status = "disconnected"; Ready = false; requestedStart = false; ConversationLive = false;
            SetPtt(false); StopCapture(); DiscardReply(); SetError(code); CloseTransport();
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
        void OnApplicationFocus(bool focused) { if (!focused) SetPtt(false); }
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
        [Serializable] sealed class BridgeState { public int epoch; public string owner; public bool outputInhibited; public string[] capabilities; public string conversationInteraction; public int conversationGeneration = -1; public ConversationSettings conversationSettings; public int conversationSettingsRevision; public string backend; public bool brainReady; public float frameAgeMs; }
        void HandleFrame(BrainFrameMessage frame) { if (frame != null) Sequence = frame.sequence; }

        [Serializable] sealed class ConversationStateMessage { public string state; public int conversationGeneration = -1; }
        [Serializable] class GenerationMessage { public int conversationGeneration = -1; }
        [Serializable] sealed class ConversationTextMessage : GenerationMessage { public string text; public string role; public bool append; }
        [Serializable] sealed class AudioMessage : GenerationMessage { public string audio; }
        [Serializable] sealed class ErrorMessage { public string error; public string requestId; }
        [Serializable] sealed class ConversationSettingsMessage { public string requestId; public ConversationSettings settings; public int revision; }
        [Serializable] sealed class ConversationStart { public string type; public string interaction; public int controlEpoch; }
        [Serializable] sealed class ConversationStop { public string type; }
        [Serializable] sealed class EmergencyStopMessage { public string type; }
        [Serializable] sealed class AudioOutbound { public string type; public int conversationGeneration; public string audio; }
        [Serializable] sealed class ConfigureConversation { public string type; public string requestId; public int controlEpoch; public int expectedRevision; public ConversationSettings settings; }
        [Serializable] public sealed class ConversationOptions { public string[] languages; public string[] voices; public string[] personas; public int maxPersonaTextLength; }
        [Serializable] sealed class BrainFrameMessage { public long sequence; }
    }
}
