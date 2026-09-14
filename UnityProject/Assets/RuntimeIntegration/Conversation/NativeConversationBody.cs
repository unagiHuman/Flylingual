using System;
using FlyBrainPoC;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Installs the existing live Brain motor source only after the controller's explicit safety gate.</summary>
    [DefaultExecutionOrder(-1000)]
    public sealed class NativeConversationBody : MonoBehaviour
    {
        const float FreshSeconds = .75f;
        const float ConnectTimeoutSeconds = 3f;
        ConversationSessionController conversation;
        WindowsReplayDemo demo;
        bool armed, bodyActive, faulted;
        int armedEpoch, boundarySequence, tcpSequence;
        float armedAt, connectedAt, lastNewFrameAt;
        BrainFrame boundaryFrame;
        Vector3 origin;

        public bool BodyActive => bodyActive;
        public int TcpSequence => tcpSequence;
        public float Displacement => demo == null || demo.body == null ? 0f : Vector3.Distance(origin, demo.body.Position);
        public string Fault { get; private set; }

        void Awake()
        {
            conversation = GetComponent<ConversationSessionController>();
            demo = FindFirstObjectByType<WindowsReplayDemo>();
            Deactivate();
        }

        void Update()
        {
            if (Flylingual.PlayScreen.TitleScreen.BlocksGameplay)
            {
                if (armed || bodyActive) Deactivate();
                return;
            }
            if (conversation == null || demo == null || demo.client == null || demo.live == null || demo.controller == null) return;
            if (!conversation.BodyControlActive)
            {
                if (armed || bodyActive) Deactivate();
                faulted = false;
                return;
            }
            if (faulted) return;
            if (!armed) Arm();
            if (conversation.ControlEpoch != armedEpoch) { Fail("body_epoch_changed"); return; }
            if (demo.client.ConnectionState != "CONNECTED")
            {
                if (connectedAt > 0f) Fail("body_tcp_disconnected");
                else if (Time.unscaledTime - armedAt >= ConnectTimeoutSeconds) Fail("body_tcp_connect_timeout");
                return;
            }
            if (connectedAt <= 0f) connectedAt = Time.unscaledTime;
            if (!demo.client.TryGetLatestFrame(out BrainFrame frame, out double age))
            {
                if (Time.unscaledTime - lastNewFrameAt >= FreshSeconds) Fail("body_tcp_frame_timeout");
                return;
            }
            // A cached frame can be fresh according to the TCP client but belongs to before this arm.
            if (ReferenceEquals(frame, boundaryFrame) || frame.sequence <= boundarySequence || frame.sequence <= tcpSequence)
            {
                if (Time.unscaledTime - lastNewFrameAt >= FreshSeconds) Fail("body_tcp_new_frame_timeout");
                return;
            }
            if (age > FreshSeconds) { Fail("body_tcp_stale"); return; }
            if (!ValidFrame(frame)) { Fail("body_tcp_invalid_frame"); return; }
            tcpSequence = frame.sequence;
            lastNewFrameAt = Time.unscaledTime;
            if (!bodyActive)
            {
                bodyActive = true;
                demo.controller.SetMotorSource(demo.live);
                Time.timeScale = 1f;
            }
        }

        void FixedUpdate()
        {
            if (!bodyActive) return;
            if (conversation == null || !conversation.BodyControlActive) { Fail("body_fixed_control_inactive"); return; }
            if (conversation.ControlEpoch != armedEpoch) { Fail("body_fixed_epoch_changed"); return; }
            if (demo == null || demo.client == null) { Fail("body_fixed_client_missing"); return; }
            if (demo.client.ConnectionState != "CONNECTED") { Fail("body_fixed_tcp_disconnected"); return; }
            if (Time.unscaledTime - lastNewFrameAt > FreshSeconds) { Fail("body_fixed_new_frame_stale"); return; }
            if (!demo.client.TryGetLatestFrame(out BrainFrame frame, out double age)) { Fail("body_fixed_frame_missing"); return; }
            if (age > FreshSeconds) { Fail("body_fixed_tcp_age_stale"); return; }
            if (frame.sequence < tcpSequence) { Fail("body_fixed_sequence_regressed"); return; }
            if (!ValidFrame(frame)) Fail("body_fixed_identity_or_motor_invalid");
        }

        void Arm()
        {
            armed = true;
            armedEpoch = conversation.ControlEpoch;
            armedAt = Time.unscaledTime;
            connectedAt = 0f;
            BrainFrame old = demo.client.LatestBrainFrame;
            boundaryFrame = old;
            boundarySequence = SameIdentity(old) ? old.sequence : int.MinValue;
            tcpSequence = boundarySequence;
            lastNewFrameAt = armedAt;
            origin = demo.body == null ? Vector3.zero : demo.body.Position;
            Fault = null;
            demo.controller.SetMotorSource(null);
            Time.timeScale = 0f;
            if (demo.client.ConnectionState != "DISCONNECTED") { Fail("body_tcp_not_released"); return; }
            try
            {
                demo.client.ConfigureEndpoint(conversation.BridgeMotorHost, conversation.BridgeMotorPort, false);
                demo.client.enabled = true;
                demo.client.Connect();
            }
            catch (Exception) { Fail("body_tcp_configure_failed"); }
        }

        bool ValidFrame(BrainFrame frame)
        {
            if (frame == null || frame.motor == null || frame.metadata == null || !Finite(frame.motor.forward) || !Finite(frame.motor.turn)) return false;
            return SameIdentity(frame);
        }
        bool SameIdentity(BrainFrame frame) => frame != null && frame.metadata != null
            && frame.metadata.sessionId == conversation.BrainSessionId && frame.metadata.instanceId == conversation.BrainInstanceId;
        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);

        void Fail(string code)
        {
            if (faulted) return;
            faulted = true;
            Fault = code;
            Deactivate();
            conversation?.BodyFault(code);
        }
        void Deactivate()
        {
            bodyActive = false;
            armed = false;
            connectedAt = 0f;
            boundaryFrame = null;
            if (demo != null)
            {
                if (demo.controller != null) demo.controller.SetMotorSource(null);
                if (demo.client != null) { demo.client.Disconnect(); demo.client.enabled = false; }
            }
            Time.timeScale = 0f;
        }
        void OnDisable() => Deactivate();
    }
}
