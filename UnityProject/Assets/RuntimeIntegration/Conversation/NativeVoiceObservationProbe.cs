using System;
using System.Collections;
using System.IO;
using System.Text;
using FlyBrainPoC;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Opt-in, passive microphone/control observation. It never sends, stops, or resets anything.</summary>
    public sealed class NativeVoiceObservationProbe : MonoBehaviour
    {
        [Serializable] sealed class Sample
        {
            public double realtimeSeconds;
            public string utc;
            public string conversationInteraction, owner, lastAppliedAction, brainSessionId, brainInstanceId, backend;
            public bool bodyControlActive, nativeBodyActive, microphoneCapturing, microphoneTransmitting, brainReady, actualFramePresent, sourceEqualsLive;
            public float inputRms, actualFrameAgeSeconds, actualMotorForward, actualMotorTurn, currentMotorForward, currentMotorTurn, yawDegrees;
            public long sentAudioChunks, receivedTranscriptDeltas, lastAppliedSequence;
            public int lastAppliedRequestId, rejectedActions, actualFrameSequence;
            public Vector3 thoraxPosition, thoraxVelocity;
            public string fault, error;
        }

        StreamWriter output;
        string directory;
        int observedRequestId;
        bool actionImageSaved;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, "-flyVoiceObserve");
            if (index < 0 || index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1])) return;
            var probe = new GameObject("Native voice observation probe").AddComponent<NativeVoiceObservationProbe>();
            probe.directory = args[index + 1];
        }

        IEnumerator Start()
        {
            Directory.CreateDirectory(directory);
            output = new StreamWriter(Path.Combine(directory, "native-voice-observation.jsonl"), false, new UTF8Encoding(false)) { AutoFlush = true };
            float deadline = Time.realtimeSinceStartup + 180f;
            while (Time.realtimeSinceStartup < deadline)
            {
                WriteSample();
                yield return new WaitForSecondsRealtime(.2f);
            }
            output.Dispose();
            output = null;
        }

        void WriteSample()
        {
            var controller = FindAnyObjectByType<ConversationSessionController>();
            var body = FindAnyObjectByType<NativeConversationBody>();
            var demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
            var sample = new Sample { realtimeSeconds = Time.realtimeSinceStartupAsDouble, utc = DateTime.UtcNow.ToString("o") };
            if (controller != null)
            {
                sample.conversationInteraction = controller.ConversationInteraction;
                sample.owner = controller.Owner;
                sample.bodyControlActive = controller.BodyControlActive;
                sample.microphoneCapturing = controller.MicrophoneCapturing;
                sample.microphoneTransmitting = controller.MicrophoneTransmitting;
                sample.inputRms = controller.InputRms;
                sample.sentAudioChunks = controller.SentAudioChunks;
                sample.receivedTranscriptDeltas = controller.ReceivedTranscriptDeltas;
                sample.lastAppliedAction = controller.LastAppliedAction;
                sample.lastAppliedRequestId = controller.LastAppliedRequestId;
                sample.lastAppliedSequence = controller.LastAppliedSequence;
                sample.rejectedActions = controller.RejectedActions;
                sample.brainSessionId = controller.BrainSessionId;
                sample.brainInstanceId = controller.BrainInstanceId;
                sample.backend = controller.Backend;
                sample.brainReady = controller.BrainReady;
                sample.error = First(controller.Error, controller.AudioError, controller.SchemaError);
                if (!actionImageSaved && controller.LastAppliedRequestId > observedRequestId)
                {
                    observedRequestId = controller.LastAppliedRequestId;
                    ScreenCapture.CaptureScreenshot(Path.Combine(directory, "action-applied.png"));
                    actionImageSaved = true;
                }
            }
            if (body != null) { sample.nativeBodyActive = body.BodyActive; sample.fault = body.Fault; }
            if (demo != null && demo.body != null)
            {
                sample.thoraxPosition = demo.body.Position;
                sample.thoraxVelocity = demo.body.LinearVelocity;
                sample.yawDegrees = demo.body.Thorax == null ? demo.body.transform.eulerAngles.y : demo.body.Thorax.transform.eulerAngles.y;
                sample.sourceEqualsLive = demo.controller != null && demo.controller.MotorSource == demo.live;
                if (demo.controller != null)
                {
                    var motor = demo.controller.CurrentMotor;
                    sample.currentMotorForward = motor.forward;
                    sample.currentMotorTurn = motor.turn;
                }
                if (demo.client != null && demo.client.TryGetLatestFrame(out BrainFrame frame, out double age) && frame != null)
                {
                    sample.actualFramePresent = true;
                    sample.actualFrameSequence = frame.sequence;
                    sample.actualFrameAgeSeconds = (float)age;
                    if (frame.motor != null) { sample.actualMotorForward = frame.motor.forward; sample.actualMotorTurn = frame.motor.turn; }
                }
            }
            output.WriteLine(JsonUtility.ToJson(sample));
        }

        static string First(params string[] values)
        {
            foreach (string value in values) if (!string.IsNullOrEmpty(value)) return value;
            return null;
        }
        void OnDestroy() { output?.Dispose(); }
    }
}
