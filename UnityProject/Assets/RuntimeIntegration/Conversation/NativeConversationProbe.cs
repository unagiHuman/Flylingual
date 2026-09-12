using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Explicit development probe: real services/API, no synthetic microphone or motor.</summary>
    public sealed class NativeConversationProbe : MonoBehaviour
    {
        [Serializable] sealed class Report
        {
            public string result, bridge, backend, error;
            public bool brainReady, outputInhibited, live, stopped, microphoneTested;
            public bool automaticStart, inputResumed, muteReleasedCapture, replyContinuedAfterMute;
            public bool microphoneDisabled;
            public int microphoneDevices, generation, settingsRevision;
            public long sequence, audioBytes, nonzeroAudioBytes, playedSamples, transcriptDeltas;
            public long playedNonzeroSamples, sentAudioChunks, sentAudioChunksDuringReply;
            public int bufferMs;
        }
        [Serializable] sealed class ActionStep
        {
            public string action, error;
            public int repeat, requestId, tcpSequence;
            public long appliedSequence;
            public bool applied, bodyActive;
            public float horizontalDisplacement, yawDegrees, motorForward, motorTurn, brainStepWallMs;
        }
        [Serializable] sealed class ActionReport
        {
            public string result = "incomplete", error, backend;
            public string brainEndpoint = "127.0.0.1:18766";
            public bool microphoneDisabled, microphoneTested, brainReady, disconnectStopped, noAutomaticResume, stopped;
            public long sentAudioChunks, sequence;
            public List<ActionStep> steps = new List<ActionStep>();
        }
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbe") < 0) return;
            new GameObject("Native conversation development probe").AddComponent<NativeConversationProbe>();
        }
        IEnumerator Start()
        {
            string path = FlyVisualDemo.WindowsReplayDemo.Argument("-flyConversationProbeOutput");
            if (string.IsNullOrEmpty(path)) { Debug.LogError("NATIVE_PROBE_OUTPUT_REQUIRED"); yield break; }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            var report = new Report { result = "startup_timeout", microphoneTested = false, bridge = "127.0.0.1" };
            ConversationSessionController controller = null;
            float deadline = Time.realtimeSinceStartup + 65;
            while (Time.realtimeSinceStartup < deadline)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                if (controller != null && controller.Ready) break;
                yield return new WaitForSecondsRealtime(.1f);
            }
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyVoiceActionsProbe") >= 0)
            {
                yield return RunActions(path, controller);
                yield break;
            }
            if (controller != null && controller.Ready)
            {
                ScreenCapture.CaptureScreenshot(Path.ChangeExtension(path, ".png"));
                report.microphoneDevices = controller.Devices.Length;
                report.microphoneDisabled = controller.MicrophoneCaptureDisabled;
                // No StartConversation/PTT call: exercise the same automatic path as the user.
                long samplesAtMute = -1;
                float unmuteAt = -1;
                deadline = Time.realtimeSinceStartup + 45;
                while (Time.realtimeSinceStartup < deadline)
                {
                    report.automaticStart |= controller.ConversationLive;
                    if (samplesAtMute < 0 && controller.PlayedNonzeroSamples >= 12000 && controller.ReplyPlaying)
                    {
                        samplesAtMute = controller.PlayedNonzeroSamples;
                        controller.SetMicrophoneMuted(true);
                        report.muteReleasedCapture = !controller.MicrophoneCapturing && !controller.MicrophoneTransmitting;
                        unmuteAt = Time.realtimeSinceStartup + .3f;
                    }
                    if (unmuteAt > 0 && Time.realtimeSinceStartup >= unmuteAt)
                    {
                        controller.SetMicrophoneMuted(false);
                        unmuteAt = -1;
                    }
                    report.replyContinuedAfterMute |= samplesAtMute >= 0 && controller.PlayedNonzeroSamples > samplesAtMute + 12000;
                    report.inputResumed |= report.replyContinuedAfterMute && controller.MicrophoneTransmitting;
                    if (report.microphoneDisabled && report.replyContinuedAfterMute && !controller.ReplyPlaying
                        && controller.ReceivedTranscriptDeltas > 0) break;
                    if (report.inputResumed && controller.SentAudioChunksDuringReply > 0 && controller.ReceivedTranscriptDeltas > 0) break;
                    yield return new WaitForSecondsRealtime(.1f);
                }
                report.backend = controller.Backend;
                report.brainReady = controller.BrainReady;
                report.outputInhibited = controller.OutputInhibited;
                report.live = controller.ConversationLive;
                report.sequence = controller.Sequence;
                report.generation = controller.ConversationGeneration;
                report.settingsRevision = controller.SettingsRevision;
                report.audioBytes = controller.ReceivedAudioBytes;
                report.nonzeroAudioBytes = controller.ReceivedNonzeroAudioBytes;
                report.transcriptDeltas = controller.ReceivedTranscriptDeltas;
                report.playedSamples = controller.PlayedSamples;
                report.playedNonzeroSamples = controller.PlayedNonzeroSamples;
                report.sentAudioChunks = controller.SentAudioChunks;
                report.sentAudioChunksDuringReply = controller.SentAudioChunksDuringReply;
                report.error = controller.Error ?? controller.AudioError;
                controller.StopConversation();
                yield return new WaitForSecondsRealtime(3);
                report.stopped = !controller.ConversationLive && !controller.IsSessionRequested && !controller.MicrophoneCapturing;
                report.bufferMs = controller.BufferedMilliseconds;
                bool replyPassed = report.live && report.nonzeroAudioBytes > 0 && report.transcriptDeltas > 0
                    && report.playedNonzeroSamples >= 24000 && report.outputInhibited && report.stopped && report.bufferMs == 0
                    && report.sequence > 1 && report.automaticStart
                    && report.muteReleasedCapture && report.replyContinuedAfterMute && string.IsNullOrEmpty(report.error);
                report.result = replyPassed && report.microphoneDisabled && report.sentAudioChunks == 0
                    ? "reply_audio_pass_no_microphone"
                    : replyPassed && report.inputResumed && report.sentAudioChunksDuringReply > 0 ? "transport_audio_pass" : "incomplete";
            }
            File.WriteAllText(path, JsonUtility.ToJson(report, true));
            Debug.Log("NATIVE_PROBE_RESULT " + report.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }

        IEnumerator RunActions(string path, ConversationSessionController controller)
        {
            var report = new ActionReport { microphoneDisabled = controller != null && controller.MicrophoneCaptureDisabled };
            var demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
            var body = controller == null ? null : controller.GetComponent<NativeConversationBody>();
            if (controller != null && controller.Ready && report.microphoneDisabled && demo != null && body != null)
            {
                ScreenCapture.CaptureScreenshot(Path.ChangeExtension(path, ".png"));
                controller.EnableVoiceActions();
                double deadline = Time.realtimeSinceStartupAsDouble + 65;
                while (Time.realtimeSinceStartupAsDouble < deadline && (controller.EnablingVoiceActions || !body.BodyActive)
                    && string.IsNullOrEmpty(controller.Error)) yield return null;
                string[] actions = { "STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L" };
                string[] phrases = { "止まって", "8秒間前に進んで", "8秒間右に曲がって", "8秒間左に曲がって", "8秒間右前に進んで", "8秒間左前に進んで" };
                for (int repeat = 1; repeat <= 3 && controller.BodyControlActive && body.BodyActive; repeat++)
                {
                    for (int i = 0; i < actions.Length && controller.BodyControlActive && body.BodyActive; i++)
                    {
                        var step = new ActionStep { action = actions[i], repeat = repeat };
                        Vector3 before = demo.body.Position;
                        float yaw = demo.body.transform.eulerAngles.y;
                        int applied = controller.AppliedActions, rejected = controller.RejectedActions;
                        controller.SendPlayerText(phrases[i]);
                        deadline = Time.realtimeSinceStartupAsDouble + 10;
                        while (Time.realtimeSinceStartupAsDouble < deadline && controller.BodyControlActive
                            && controller.RejectedActions == rejected && !(controller.AppliedActions > applied
                                && controller.LastAppliedAction == actions[i] && controller.LastAppliedSequence > 0
                                && body.TcpSequence >= controller.LastAppliedSequence)) yield return null;
                        step.applied = controller.AppliedActions > applied && controller.LastAppliedAction == actions[i]
                            && controller.LastAppliedSequence > 0 && body.TcpSequence >= controller.LastAppliedSequence;
                        step.requestId = controller.LastAppliedRequestId;
                        step.appliedSequence = controller.LastAppliedSequence;
                        deadline = Time.realtimeSinceStartupAsDouble + 1;
                        while (step.applied && controller.BodyControlActive && Time.realtimeSinceStartupAsDouble < deadline)
                        {
                            var frame = demo.client.LatestBrainFrame;
                            if (frame != null && frame.motor != null)
                            {
                                step.motorForward = frame.motor.forward;
                                step.motorTurn = frame.motor.turn;
                                step.brainStepWallMs = frame.performance == null ? 0 : frame.performance.stepWallTimeMs;
                            }
                            yield return null;
                        }
                        Vector3 delta = demo.body.Position - before;
                        step.horizontalDisplacement = new Vector2(delta.x, delta.z).magnitude;
                        step.yawDegrees = Mathf.DeltaAngle(yaw, demo.body.transform.eulerAngles.y);
                        step.tcpSequence = body.TcpSequence;
                        step.bodyActive = body.BodyActive;
                        step.error = controller.Error;
                        report.steps.Add(step);
                        File.WriteAllText(path, JsonUtility.ToJson(report, true));
                        Debug.Log("NATIVE_ACTION_STEP " + actions[i] + " repeat=" + repeat + " applied=" + step.applied);
                        if (!step.applied || !step.bodyActive) break;
                        if (actions[i] != "STOP")
                        {
                            applied = controller.AppliedActions;
                            controller.SendPlayerText("止まって");
                            deadline = Time.realtimeSinceStartupAsDouble + 8;
                            while (Time.realtimeSinceStartupAsDouble < deadline && controller.BodyControlActive
                                && !(controller.AppliedActions > applied && controller.LastAppliedAction == "STOP")) yield return null;
                            if (controller.AppliedActions <= applied || controller.LastAppliedAction != "STOP") break;
                        }
                    }
                }
                report.backend = controller.Backend;
                report.brainReady = controller.BrainReady;
                report.sequence = controller.Sequence;
                report.error = controller.Error;
                if (body.BodyActive)
                {
                    demo.client.Disconnect();
                    yield return new WaitForSecondsRealtime(.3f);
                    report.disconnectStopped = !body.BodyActive && !controller.BodyControlActive && Time.timeScale == 0;
                    yield return new WaitForSecondsRealtime(2);
                    report.noAutomaticResume = !body.BodyActive && !controller.BodyControlActive;
                }
                controller.EmergencyStop();
                yield return new WaitForSecondsRealtime(3);
                report.stopped = !body.BodyActive && !controller.ConversationLive && controller.BufferedMilliseconds == 0;
                report.sentAudioChunks = controller.SentAudioChunks;
                report.result = report.steps.Count == 18 && report.steps.TrueForAll(step => step.applied && step.bodyActive)
                    && report.disconnectStopped && report.noAutomaticResume && report.stopped && report.sentAudioChunks == 0
                    ? "native_actions_transport_pass" : "incomplete";
            }
            else report.error = "action_probe_requires_no_microphone_and_real_body";
            File.WriteAllText(path, JsonUtility.ToJson(report, true));
            Debug.Log("NATIVE_ACTION_RESULT " + report.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }
    }
}
