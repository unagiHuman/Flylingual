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
            public string action, error, brainSessionId, brainInstanceId;
            public int repeat, requestId, tcpSequence;
            public long appliedSequence;
            public bool applied, bodyActive, sourceMaintained, phaseAdvanced, movementPassed, forwardPassed, groundedPassed, heightPassed, turnPassed, stopSettled, validationPassed;
            public int sampleCount, groundedSampleCount, attachedMax, groundContactMax, stopTailSampleCount;
            public float horizontalDisplacement, forwardDisplacement, forwardProjectedTravel, lateralDisplacement, endHeightDelta;
            public float yawDegrees, motorForward, motorTurn, brainStepWallMs, frameAgeMaxSeconds;
            public float currentMotorForwardPeakAbs, currentMotorTurnPeakAbs, finalCurrentMotorForward, finalCurrentMotorTurn;
            public float phaseStartRadians, phaseEndRadians, phaseAbsoluteTravelRadians, thoraxSpeedMax;
            public Vector3 startPosition, endPosition;
        }
        [Serializable] sealed class ActionReport
        {
            public string result = "incomplete", error, backend;
            public string brainEndpoint = "127.0.0.1:18766";
            public bool microphoneDisabled, microphoneTested, brainReady, disconnectStopped, noAutomaticResume, stopped, automaticVoiceControl, sourceMaintainedDuringPreparation = true;
            public bool ttlWaitReady, disconnectRecovered, recoveredStopped;
            public long sentAudioChunks, sequence;
            public int physicsResetCount, initialGroundContactCount, continuousExpiryChecks;
            public string physicsResetMethod;
            public Vector3 initialRootPosition;
            public Quaternion initialRootRotation;
            public float initialPhaseRadians;
            public List<ActionStep> steps = new List<ActionStep>();
        }
        sealed class PhysicsBaseline
        {
            public Vector3 rootPosition;
            public Quaternion rootRotation;
            public List<float> jointPositions;
            public float phaseRadians;
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
                double deadline = Time.realtimeSinceStartupAsDouble + 65;
                while (Time.realtimeSinceStartupAsDouble < deadline && (controller.EnablingVoiceActions || !body.BodyActive)
                    && string.IsNullOrEmpty(controller.Error)) yield return null;
                report.automaticVoiceControl = body.BodyActive && controller.BodyControlActive && !controller.EnablingVoiceActions;
                if (!report.automaticVoiceControl && string.IsNullOrEmpty(report.error))
                    report.error = "automatic_voice_control_timeout";
                string[] actions = { "STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L" };
                string[] phrases = { "止まって", "8秒間前に進んで", "8秒間右に曲がって", "8秒間左に曲がって", "8秒間右前に進んで", "8秒間左前に進んで" };
                var baseline = new PhysicsBaseline();
                bool initialStopReady = false;
                yield return WaitForAppliedBrainStop(controller, body, demo, 20, ready => initialStopReady = ready);
                bool initialGrounded = false;
                if (initialStopReady)
                    yield return WaitForGroundSettle(demo, 1, 20, ready => initialGrounded = ready);
                report.sourceMaintainedDuringPreparation &= demo.controller.MotorSource == demo.live;
                if (!initialStopReady || !initialGrounded)
                {
                    report.error = initialStopReady ? "initial_ground_settle_timeout" : "initial_brain_stop_timeout";
                }
                else
                {
                    CaptureBaseline(demo, baseline, report);
                    bool expiryPassed = false;
                    yield return VerifyContinuousExpiry(controller, body, demo, baseline, report, ready => expiryPassed = ready);
                    if (!expiryPassed)
                    {
                        if (string.IsNullOrEmpty(report.error)) report.error = "continuous_ttl_recovery_failed";
                    }
                    else
                    {
                        bool abortCases = false;
                        for (int repeat = 1; repeat <= 3 && !abortCases && controller.BodyControlActive && body.BodyActive; repeat++)
                        {
                            for (int i = 0; i < actions.Length && !abortCases && controller.BodyControlActive && body.BodyActive; i++)
                            {
                                bool stopReady = false;
                                yield return WaitForAppliedBrainStop(controller, body, demo, 20, ready => stopReady = ready);
                                report.sourceMaintainedDuringPreparation &= demo.controller.MotorSource == demo.live;
                                if (!stopReady)
                                {
                                    report.steps.Add(new ActionStep { action = actions[i], repeat = repeat, error = "case_brain_stop_timeout" });
                                    abortCases = true;
                                    break;
                                }
                                RestoreBaseline(demo, baseline);
                                report.physicsResetCount++;
                                bool groundReady = false;
                                yield return WaitForGroundSettle(demo, 1, 20, ready => groundReady = ready);
                                report.sourceMaintainedDuringPreparation &= demo.controller.MotorSource == demo.live;
                                if (!groundReady)
                                {
                                    report.steps.Add(new ActionStep { action = actions[i], repeat = repeat, error = "case_ground_settle_timeout" });
                                    abortCases = true;
                                    break;
                                }
                                var step = new ActionStep { action = actions[i], repeat = repeat, sourceMaintained = report.sourceMaintainedDuringPreparation };
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
                                step.startPosition = demo.body.Position;
                                Transform thoraxTransform = demo.body.Thorax == null ? demo.body.transform : demo.body.Thorax.transform;
                                Vector3 startForward = Vector3.ProjectOnPlane(thoraxTransform.forward, Vector3.up).normalized;
                                Vector3 startRight = Vector3.ProjectOnPlane(thoraxTransform.right, Vector3.up).normalized;
                                Vector3 previousPosition = step.startPosition;
                                float previousYaw = thoraxTransform.eulerAngles.y;
                                step.phaseStartRadians = demo.controller.Phase;
                                float previousPhase = step.phaseStartRadians;
                                // The voice intent permits eight seconds.  Three seconds gives the
                                // smoothed CPG and the physical stance/swing cycle time to manifest.
                                deadline = Time.realtimeSinceStartupAsDouble + 3;
                                double stopTailAt = deadline - .5;
                                bool stopTailSettled = true;
                                while (step.applied && controller.BodyControlActive && Time.realtimeSinceStartupAsDouble < deadline)
                                {
                                    var frame = demo.client.LatestBrainFrame;
                                    if (frame != null && frame.motor != null)
                                    {
                                        step.motorForward = frame.motor.forward;
                                        step.motorTurn = frame.motor.turn;
                                        step.brainStepWallMs = frame.performance == null ? 0 : frame.performance.stepWallTimeMs;
                                        step.brainSessionId = frame.metadata == null ? null : frame.metadata.sessionId;
                                        step.brainInstanceId = frame.metadata == null ? null : frame.metadata.instanceId;
                                    }
                                    step.sampleCount++;
                                    step.sourceMaintained &= demo.controller.MotorSource == demo.live;
                                    var currentMotor = demo.controller.CurrentMotor;
                                    step.currentMotorForwardPeakAbs = Mathf.Max(step.currentMotorForwardPeakAbs, Mathf.Abs(currentMotor.forward));
                                    step.currentMotorTurnPeakAbs = Mathf.Max(step.currentMotorTurnPeakAbs, Mathf.Abs(currentMotor.turn));
                                    step.finalCurrentMotorForward = currentMotor.forward;
                                    step.finalCurrentMotorTurn = currentMotor.turn;
                                    step.groundContactMax = Mathf.Max(step.groundContactMax, demo.body.GroundContactCount);
                                    if (demo.body.GroundContactCount > 0) step.groundedSampleCount++;
                                    int attached = 0;
                                    foreach (var leg in demo.body.Legs) if (leg != null && leg.FootAdhesion != null && leg.FootAdhesion.Attached) attached++;
                                    step.attachedMax = Mathf.Max(step.attachedMax, attached);
                                    step.thoraxSpeedMax = Mathf.Max(step.thoraxSpeedMax, demo.body.LinearVelocity.magnitude);
                                    if (!double.IsInfinity(demo.live.LatestFrameAgeSeconds) && !double.IsNaN(demo.live.LatestFrameAgeSeconds))
                                        step.frameAgeMaxSeconds = Mathf.Max(step.frameAgeMaxSeconds, (float)demo.live.LatestFrameAgeSeconds);
                                    float phase = demo.controller.Phase;
                                    step.phaseAbsoluteTravelRadians += Mathf.Abs(Mathf.DeltaAngle(previousPhase * Mathf.Rad2Deg, phase * Mathf.Rad2Deg)) * Mathf.Deg2Rad;
                                    previousPhase = phase;
                                    Transform currentThorax = demo.body.Thorax == null ? demo.body.transform : demo.body.Thorax.transform;
                                    Vector3 position = demo.body.Position;
                                    Vector3 horizontalStep = Vector3.ProjectOnPlane(position - previousPosition, Vector3.up);
                                    Vector3 currentForward = Vector3.ProjectOnPlane(currentThorax.forward, Vector3.up).normalized;
                                    step.forwardProjectedTravel += Vector3.Dot(horizontalStep, currentForward);
                                    previousPosition = position;
                                    float yaw = currentThorax.eulerAngles.y;
                                    step.yawDegrees += Mathf.DeltaAngle(previousYaw, yaw);
                                    previousYaw = yaw;
                                    if (actions[i] == "STOP" && Time.realtimeSinceStartupAsDouble >= stopTailAt)
                                    {
                                        step.stopTailSampleCount++;
                                        Vector3 velocity = Vector3.ProjectOnPlane(demo.body.LinearVelocity, Vector3.up);
                                        stopTailSettled &= velocity.magnitude < .05f
                                            && Mathf.Abs(currentMotor.forward) < .03f && Mathf.Abs(currentMotor.turn) < .03f;
                                    }
                                    yield return null;
                                }
                                step.endPosition = demo.body.Position;
                                Vector3 delta = step.endPosition - step.startPosition;
                                step.horizontalDisplacement = new Vector2(delta.x, delta.z).magnitude;
                                Vector3 horizontalDelta = Vector3.ProjectOnPlane(delta, Vector3.up);
                                step.forwardDisplacement = Vector3.Dot(horizontalDelta, startForward);
                                step.lateralDisplacement = Vector3.Dot(horizontalDelta, startRight);
                                step.endHeightDelta = step.endPosition.y - baseline.rootPosition.y;
                                step.phaseEndRadians = demo.controller.Phase;
                                step.tcpSequence = body.TcpSequence;
                                step.bodyActive = body.BodyActive;
                                // STOP deliberately freezes the CPG; every commanded movement
                                // must advance it, while STOP is checked by its settled motor.
                                step.phaseAdvanced = actions[i] == "STOP" || step.phaseAbsoluteTravelRadians > .1f;
                                bool forwardAction = actions[i] == "FORWARD" || actions[i] == "FORWARD_R" || actions[i] == "FORWARD_L";
                                // Curved forward-turn trials can face beyond the start tangent; use
                                // accumulated local-forward travel there, while pure FORWARD must
                                // finish ahead of its starting body direction.
                                step.forwardPassed = !forwardAction || (actions[i] == "FORWARD"
                                    ? step.forwardDisplacement > .001f : step.forwardProjectedTravel > .001f);
                                step.movementPassed = !forwardAction || (step.horizontalDisplacement > .001f && step.forwardPassed);
                                step.groundedPassed = step.groundedSampleCount > 0;
                                step.heightPassed = step.endHeightDelta >= -.5f;
                                int turnSign = actions[i].EndsWith("_R") ? 1 : actions[i].EndsWith("_L") ? -1 : 0;
                                step.turnPassed = turnSign == 0 || (turnSign > 0 ? step.yawDegrees > .1f : step.yawDegrees < -.1f);
                                step.stopSettled = actions[i] != "STOP" || (step.stopTailSampleCount > 0 && stopTailSettled);
                                step.validationPassed = step.applied && step.bodyActive && step.sampleCount > 0 && step.sourceMaintained
                                    && step.phaseAdvanced && step.movementPassed && step.groundedPassed && step.heightPassed && step.turnPassed && step.stopSettled;
                                step.error = controller.Error;
                                if (!step.validationPassed && string.IsNullOrEmpty(step.error))
                                    step.error = "motion_validation_failed";
                                report.steps.Add(step);
                                File.WriteAllText(path, JsonUtility.ToJson(report, true));
                                if (repeat == 1)
                                    ScreenCapture.CaptureScreenshot(Path.Combine(Path.GetDirectoryName(path), "motion-" + actions[i] + ".png"));
                                Debug.Log("NATIVE_ACTION_STEP " + actions[i] + " repeat=" + repeat + " applied=" + step.applied + " motion=" + step.validationPassed);
                                if (!controller.BodyControlActive || !step.bodyActive) break;
                            }
                        }
                    }
                }
                report.backend = controller.Backend;
                report.brainReady = controller.BrainReady;
                report.sequence = controller.Sequence;
                if (string.IsNullOrEmpty(report.error)) report.error = controller.Error;
                if (body.BodyActive)
                {
                    bool finalStopReady = false;
                    yield return WaitForAppliedBrainStop(controller, body, demo, 20, ready => finalStopReady = ready);
                    report.sourceMaintainedDuringPreparation &= demo.controller.MotorSource == demo.live;
                    if (!finalStopReady && string.IsNullOrEmpty(report.error)) report.error = "final_brain_stop_timeout";
                    demo.client.Disconnect();
                    yield return new WaitForSecondsRealtime(.3f);
                    report.disconnectStopped = !body.BodyActive && !controller.BodyControlActive && Time.timeScale == 0;
                    double recoveryDeadline = Time.realtimeSinceStartupAsDouble + 45;
                    while (Time.realtimeSinceStartupAsDouble < recoveryDeadline)
                    {
                        if (controller.BodyControlActive && body.BodyActive && demo.controller.MotorSource == demo.live
                            && demo.client.TryGetLatestFrame(out var frame, out double age) && frame != null && frame.motor != null
                            && age <= .75 && frame.requestedAction == "STOP"
                            && Mathf.Abs(frame.motor.forward) <= .02f && Mathf.Abs(frame.motor.turn) <= .02f)
                        {
                            report.disconnectRecovered = report.recoveredStopped = true;
                            break;
                        }
                        yield return null;
                    }
                    if (!report.disconnectRecovered && string.IsNullOrEmpty(report.error)) report.error = "disconnect_recovery_timeout";
                    if (report.disconnectRecovered && report.error != null && report.error.StartsWith("body_", StringComparison.Ordinal)) report.error = null;
                }
                controller.EmergencyStop();
                yield return new WaitForSecondsRealtime(3);
                report.stopped = !body.BodyActive && !controller.ConversationLive && controller.BufferedMilliseconds == 0;
                report.noAutomaticResume = !body.BodyActive && !controller.BodyControlActive && demo.controller.MotorSource != demo.live;
                report.sentAudioChunks = controller.SentAudioChunks;
                report.result = report.steps.Count == 18 && report.steps.TrueForAll(step => step.validationPassed)
                    && report.automaticVoiceControl && report.ttlWaitReady && report.continuousExpiryChecks == 3
                    && report.sourceMaintainedDuringPreparation && report.disconnectStopped && report.disconnectRecovered && report.recoveredStopped && report.noAutomaticResume
                    && report.stopped && report.sentAudioChunks == 0 && string.IsNullOrEmpty(report.error)
                    ? "native_actions_motion_pass" : "incomplete";
            }
            else report.error = "action_probe_requires_no_microphone_and_real_body";
            File.WriteAllText(path, JsonUtility.ToJson(report, true));
            Debug.Log("NATIVE_ACTION_RESULT " + report.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }

        static IEnumerator VerifyContinuousExpiry(ConversationSessionController controller, NativeConversationBody body,
                                                   FlyVisualDemo.WindowsReplayDemo demo, PhysicsBaseline baseline,
                                                   ActionReport report, Action<bool> completed)
        {
            report.ttlWaitReady = true;
            for (int check = 0; check < 3; check++)
            {
                bool stopReady = false;
                yield return WaitForAppliedBrainStop(controller, body, demo, 20, ready => stopReady = ready);
                if (!stopReady) { report.error = "ttl_setup_stop_timeout"; completed(false); yield break; }
                RestoreBaseline(demo, baseline);
                report.physicsResetCount++;
                bool groundReady = false;
                yield return WaitForGroundSettle(demo, 1, 20, ready => groundReady = ready);
                if (!groundReady) { report.error = "ttl_setup_ground_timeout"; completed(false); yield break; }

                int epoch = controller.ControlEpoch;
                int generation = controller.ConversationGeneration;
                int appliedBefore = controller.AppliedActions;
                int rejectedBefore = controller.RejectedActions;
                Vector3 origin = demo.body.Position;
                controller.SendPlayerText("8秒間前に進んで");
                double deadline = Time.realtimeSinceStartupAsDouble + 10;
                while (Time.realtimeSinceStartupAsDouble < deadline && controller.BodyControlActive
                    && controller.RejectedActions == rejectedBefore && !(controller.AppliedActions > appliedBefore
                        && controller.LastAppliedAction == "FORWARD" && controller.LastAppliedSequence > 0
                        && body.TcpSequence >= controller.LastAppliedSequence)) yield return null;
                bool forwardApplied = controller.AppliedActions > appliedBefore && controller.LastAppliedAction == "FORWARD"
                    && controller.LastAppliedSequence > 0 && body.TcpSequence >= controller.LastAppliedSequence;
                if (!forwardApplied) { report.error = "ttl_forward_not_applied"; completed(false); yield break; }

                deadline = Time.realtimeSinceStartupAsDouble + 1;
                while (Time.realtimeSinceStartupAsDouble < deadline && controller.BodyControlActive && body.BodyActive) yield return null;
                bool moved = Vector3.ProjectOnPlane(demo.body.Position - origin, Vector3.up).magnitude > .001f;
                int appliedAfterForward = controller.AppliedActions;
                bool settledStop = false, stableControl = true, noReplay = true;
                deadline = Time.realtimeSinceStartupAsDouble + 8;
                while (Time.realtimeSinceStartupAsDouble < deadline)
                {
                    stableControl &= controller.ContinuousVoiceControl && controller.ControlEpoch == epoch
                        && controller.ConversationGeneration == generation && controller.BodyControlActive && body.BodyActive
                        && demo.controller.MotorSource == demo.live;
                    noReplay &= controller.AppliedActions == appliedAfterForward;
                    if (demo.client.TryGetLatestFrame(out var frame, out double age) && frame != null && frame.motor != null)
                        settledStop |= age <= .75 && frame.requestedAction == "STOP"
                            && Mathf.Abs(frame.motor.forward) <= .02f && Mathf.Abs(frame.motor.turn) <= .02f;
                    yield return null;
                }
                report.continuousExpiryChecks++;
                bool passed = moved && settledStop && stableControl && noReplay;
                report.ttlWaitReady &= passed;
                if (!passed) { report.error = "ttl_continuity_check_failed"; completed(false); yield break; }
            }
            completed(true);
        }

        static IEnumerator WaitForAppliedBrainStop(ConversationSessionController controller, NativeConversationBody body,
                                                    FlyVisualDemo.WindowsReplayDemo demo, float timeoutSeconds,
                                                    Action<bool> completed)
        {
            int appliedBefore = controller.AppliedActions;
            controller.SendPlayerText("止まって");
            double deadline = Time.realtimeSinceStartupAsDouble + timeoutSeconds;
            double stableSince = -1;
            while (Time.realtimeSinceStartupAsDouble < deadline && controller.BodyControlActive && body.BodyActive)
            {
                bool applied = controller.AppliedActions > appliedBefore && controller.LastAppliedAction == "STOP"
                    && controller.LastAppliedSequence > 0 && body.TcpSequence >= controller.LastAppliedSequence;
                var frame = demo.client.LatestBrainFrame;
                bool zeroBrainMotor = frame != null && frame.motor != null
                    && Mathf.Abs(frame.motor.forward) < .01f && Mathf.Abs(frame.motor.turn) < .01f;
                if (applied && zeroBrainMotor)
                {
                    if (stableSince < 0) stableSince = Time.realtimeSinceStartupAsDouble;
                    if (Time.realtimeSinceStartupAsDouble - stableSince >= .5)
                    {
                        completed(true);
                        yield break;
                    }
                }
                else stableSince = -1;
                if (!string.IsNullOrEmpty(controller.Error)) break;
                yield return null;
            }
            completed(false);
        }

        static IEnumerator WaitForGroundSettle(FlyVisualDemo.WindowsReplayDemo demo, float settleSeconds,
                                               float timeoutSeconds, Action<bool> completed)
        {
            double deadline = Time.realtimeSinceStartupAsDouble + timeoutSeconds;
            double groundedSince = -1;
            while (Time.realtimeSinceStartupAsDouble < deadline)
            {
                if (demo.body.GroundContactCount >= 5)
                {
                    if (groundedSince < 0) groundedSince = Time.realtimeSinceStartupAsDouble;
                    if (Time.realtimeSinceStartupAsDouble - groundedSince >= settleSeconds)
                    {
                        completed(true);
                        yield break;
                    }
                }
                else groundedSince = -1;
                yield return null;
            }
            completed(false);
        }

        static void CaptureBaseline(FlyVisualDemo.WindowsReplayDemo demo, PhysicsBaseline baseline, ActionReport report)
        {
            var root = demo.body.Thorax;
            baseline.rootPosition = root.transform.position;
            baseline.rootRotation = root.transform.rotation;
            baseline.jointPositions = new List<float>();
            root.GetJointPositions(baseline.jointPositions);
            baseline.phaseRadians = demo.controller.Phase;
            report.initialRootPosition = baseline.rootPosition;
            report.initialRootRotation = baseline.rootRotation;
            report.initialPhaseRadians = baseline.phaseRadians;
            report.initialGroundContactCount = demo.body.GroundContactCount;
            report.physicsResetMethod = "TeleportRoot+joint_positions+zero_velocities+preset_adhesion+reflex_reset+phase_restore+expire_contact_hold";
        }

        static void RestoreBaseline(FlyVisualDemo.WindowsReplayDemo demo, PhysicsBaseline baseline)
        {
            var root = demo.body.Thorax;
            root.TeleportRoot(baseline.rootPosition, baseline.rootRotation);
            root.SetJointPositions(new List<float>(baseline.jointPositions));
            var zeros = new List<float>(baseline.jointPositions.Count);
            for (int i = 0; i < baseline.jointPositions.Count; i++) zeros.Add(0);
            root.SetJointVelocities(zeros);
            root.SetJointForces(zeros);
            root.linearVelocity = Vector3.zero;
            root.angularVelocity = Vector3.zero;
            foreach (var rigidbody in demo.body.GetComponentsInChildren<Rigidbody>())
            {
                rigidbody.linearVelocity = Vector3.zero;
                rigidbody.angularVelocity = Vector3.zero;
            }
            foreach (var leg in demo.body.Legs)
            {
                if (leg == null) continue;
                leg.Coxa.SetTarget(0);
                leg.Femur.SetTarget(0);
                leg.Tibia.SetTarget(0);
            }
            var preset = demo.gameplayPreset;
            demo.controller.ConfigureFootAdhesion(true, preset.normalAdhesion, preset.shearAdhesion,
                                                  preset.attachDelay, preset.detachThreshold);
            if (demo.controller.ReflexLayer != null) demo.controller.ReflexLayer.ResetState();
            demo.controller.SetPhaseForDiagnostics(baseline.phaseRadians);
            Physics.SyncTransforms();
            foreach (var leg in demo.body.Legs)
            {
                if (leg == null || leg.FootContact == null) continue;
                for (int i = 0; i < 3; i++) leg.FootContact.AdvanceAdhesionTick();
            }
        }
    }
}
