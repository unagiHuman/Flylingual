using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.UIElements;

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
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbe") < 0
                && Array.IndexOf(Environment.GetCommandLineArgs(), "-flyEnglishRouteProbe") < 0
                && Array.IndexOf(Environment.GetCommandLineArgs(), "-flyFullCourseProbe") < 0) return;
            new GameObject("Native conversation development probe").AddComponent<NativeConversationProbe>();
        }
        IEnumerator Start()
        {
            string path = FlyVisualDemo.WindowsReplayDemo.Argument("-flyConversationProbeOutput");
            if (string.IsNullOrEmpty(path)) { Debug.LogError("NATIVE_PROBE_OUTPUT_REQUIRED"); yield break; }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyFullCourseProbe") >= 0)
            {
                yield return RunFullCourseProbe(path);
                yield break;
            }
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyEnglishRouteProbe") >= 0)
            {
                yield return RunEnglishRouteProbe(path);
                yield break;
            }            var report = new Report { result = "startup_timeout", microphoneTested = false, bridge = "127.0.0.1" };
            // Exercise the normal title/tutorial buttons before waiting for auto-start.
            yield return null;
            var title = FindAnyObjectByType<Flylingual.PlayScreen.TitleScreen>();
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyTitleConnectionProbe") >= 0)
            {
                yield return RunTitleConnectionProbe(path, title);
                yield break;
            }
            if (title != null && Flylingual.PlayScreen.TitleScreen.BlocksGameplay)
            {
                float titleDeadline = Time.realtimeSinceStartup + 90;
                while (!title.CanStart && Time.realtimeSinceStartup < titleDeadline) yield return null;
                title.StartGame(); yield return null;
                if (Flylingual.PlayScreen.TitleScreen.BlocksGameplay) { title.StartGame(); yield return null; }
            }
            ConversationSessionController controller = null;
            float deadline = Time.realtimeSinceStartup + 65;
            while (Time.realtimeSinceStartup < deadline)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                if (controller != null && controller.Ready) break;
                yield return new WaitForSecondsRealtime(.1f);
            }
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyDemoAssistProbe") >= 0)
            {
                yield return RunDemoAssistProbe(path, controller);
                yield break;
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

        [Serializable] sealed class FullCourseRequest
        {
            public string text, action;
            public float requestedAt, appliedAt;
            public int appliedRequestId;
            public long appliedSequence;
            public bool applied;
        }
        [Serializable] sealed class FullCourseSample
        {
            public float elapsed, frameAgeMs;
            public Vector3 position, waypoint;
            public string stage, recommendation, appliedAction, error, protocolError, executionId;
            public long sequence;
            public bool waypointValid, ready, rawBrainReady, freshBrain, liveSource;
        }
        [Serializable] sealed class FullCourseReport
        {
            public string result = "incomplete", error, backend, finalStage;
            public string brainEndpoint = "127.0.0.1:18766";
            public string method = "Scripted normal player text following authored route; not evidence that arbitrary human instructions clear the course";
            public bool titleStarted, microphoneDisabled, goalConfirmed, revealComplete, finalStopped;
            public bool liveSourceMaintained = true, freshBrainMaintained = true;
            public int attempt, deaths;
            public float elapsed, travelledMeters;
            public Vector3 initialPosition, finalPosition;
            public List<FullCourseRequest> requests = new List<FullCourseRequest>();
            public List<FullCourseSample> samples = new List<FullCourseSample>();
        }

        IEnumerator RunFullCourseProbe(string path)
        {
            var r = new FullCourseReport();
            float began = Time.realtimeSinceStartup, finish = began + 600;
            float until = began + 90;
            ConversationSessionController c = null;
            Flylingual.PlayScreen.TitleScreen title = null;
            while (Time.realtimeSinceStartup < until)
            {
                c = FindAnyObjectByType<ConversationSessionController>();
                title = FindAnyObjectByType<Flylingual.PlayScreen.TitleScreen>();
                if (title != null && title.CanStart && c != null) break;
                yield return null;
            }
            var demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
            var stage = FindAnyObjectByType<Flylingual.BlindSugarRun.BlindSugarRunSession>();
            var route = stage == null ? null : stage.GetComponent<Flylingual.BlindSugarRun.BlindSugarRunRouteHint>();
            var body = c == null ? null : c.GetComponent<NativeConversationBody>();
            r.initialPosition = demo == null || demo.body == null ? Vector3.zero : demo.body.Position;
            if (title != null && title.CanStart)
            {
                title.StartGame(); yield return null;
                if (Flylingual.PlayScreen.TitleScreen.BlocksGameplay) { title.StartGame(); yield return null; }
            }
            r.titleStarted = !Flylingual.PlayScreen.TitleScreen.BlocksGameplay;
            r.microphoneDisabled = c != null && c.MicrophoneCaptureDisabled;
            if (!r.titleStarted || !r.microphoneDisabled || c == null || !c.BodyControlActive
                || stage == null || route == null || body == null || demo == null || demo.body == null
                || demo.controller == null || demo.live == null)
                r.error = "full_course_requires_ready_real_body_route_and_no_microphone";
            else
            {
                FullCourseRequest pending = null;
                int appliedBefore = c.AppliedActions;
                float nextSample = 0, unavailableSince = -1, nextRequestAt = Time.realtimeSinceStartup + 1;
                Vector3 previousPosition = demo.body.Position;
                Action<string> request = action =>
                {
                    string text = action == "FORWARD" ? "Move forward for 6 seconds"
                        : action == "TURN_R" ? "Turn right for 1 second"
                        : action == "TURN_L" ? "Turn left for 1 second" : "Stop";
                    pending = new FullCourseRequest { action = action, text = text, requestedAt = Time.realtimeSinceStartup - began };
                    r.requests.Add(pending); appliedBefore = c.AppliedActions;
                    c.SendPlayerText(text); nextRequestAt = Time.realtimeSinceStartup + .3f;
                    File.WriteAllText(path, JsonUtility.ToJson(r, true));
                };
                while (Time.realtimeSinceStartup < finish)
                {
                    float now = Time.realtimeSinceStartup;
                    var state = stage.State;
                    var reveal = stage.GetComponent<Flylingual.BlindSugarRun.BlindSugarRunReveal>();
                    r.goalConfirmed |= state == Flylingual.BlindSugarRun.BlindSugarRunSession.StageState.Goal
                        || state == Flylingual.BlindSugarRun.BlindSugarRunSession.StageState.Reveal;
                    r.revealComplete |= r.goalConfirmed && reveal != null && reveal.Complete;
                    bool playing = state == Flylingual.BlindSugarRun.BlindSugarRunSession.StageState.Playing;
                    bool liveSource = demo.controller.MotorSource == demo.live;
                    if (playing)
                    {
                        r.liveSourceMaintained &= liveSource;
                        r.freshBrainMaintained &= c.HasFreshBrain;
                    }
                    Vector3 point;
                    bool valid = route.TryGetWaypoint(out point);
                    string desired = route.RecommendedAction;
                    Vector3 position = demo.body.Position;
                    r.travelledMeters += Vector3.ProjectOnPlane(position - previousPosition, Vector3.up).magnitude;
                    previousPosition = position;
                    if (now >= nextSample)
                    {
                        r.samples.Add(new FullCourseSample { elapsed = now - began, position = position, waypoint = point,
                            waypointValid = valid, recommendation = desired, stage = state.ToString(), sequence = c.Sequence,
                            appliedAction = c.LastAppliedAction, executionId = c.ActiveExecution?.executionId,
                            ready = c.Ready, rawBrainReady = c.BrainReady, freshBrain = c.HasFreshBrain,
                            frameAgeMs = c.FrameAgeMs, liveSource = liveSource, error = c.Error, protocolError = c.SchemaError });
                        r.elapsed = now - began; r.finalPosition = position; r.finalStage = state.ToString();
                        File.WriteAllText(path, JsonUtility.ToJson(r, true)); nextSample = now + 1;
                    }
                    if (r.revealComplete) break;
                    if (r.goalConfirmed) { yield return null; continue; }
                    if (!playing) { r.error = "stage_" + state; break; }
                    if (!c.HasFreshBrain || !liveSource || !c.BodyControlActive || !body.BodyActive
                        || !string.IsNullOrEmpty(c.SchemaError) || !string.IsNullOrEmpty(body.Fault))
                    { r.error = c.SchemaError ?? body.Fault ?? c.Error ?? "live_body_or_freshness_lost"; break; }
                    if (pending != null && !pending.applied)
                    {
                        pending.applied = c.AppliedActions > appliedBefore && c.LastAppliedAction == pending.action
                            && c.LastAppliedSequence > 0 && body.TcpSequence >= c.LastAppliedSequence;
                        if (pending.applied)
                        {
                            pending.appliedAt = now - began; pending.appliedRequestId = c.LastAppliedRequestId;
                            pending.appliedSequence = c.LastAppliedSequence;
                        }
                        else if (now - began - pending.requestedAt > 15)
                        { r.error = "action_apply_timeout_" + pending.action; break; }
                    }
                    if (!valid || desired == null)
                    {
                        if (unavailableSince < 0) unavailableSince = now;
                        if (now - unavailableSince > 20) { r.error = "route_hint_unavailable"; break; }
                        desired = "STOP";
                    }
                    else unavailableSince = -1;
                    if (pending != null && pending.applied)
                    {
                        // Stop takes priority when the observed route changes or becomes unsafe.
                        if (pending.action != "STOP" && desired != pending.action && now >= nextRequestAt)
                            request("STOP");
                        else if (c.ActiveExecution == null && now - began - pending.appliedAt >= .5f)
                            pending = null;
                    }
                    if (pending == null && now >= nextRequestAt)
                    {
                        if (desired == "STOP" && c.LastAppliedAction == "STOP") nextRequestAt = now + .3f;
                        else request(desired);
                    }
                    yield return null;
                }
                if (!r.revealComplete && string.IsNullOrEmpty(r.error)) r.error = "full_course_timeout_600s";
                r.backend = c.Backend; r.finalStage = stage.State.ToString(); r.attempt = stage.Attempt; r.deaths = stage.Deaths;
                r.finalPosition = demo.body.Position;
            }
            if (c != null)
            {
                c.EmergencyStop();
                until = Time.realtimeSinceStartup + 3;
                while (Time.realtimeSinceStartup < until && (c.BodyControlActive || c.ConversationActive)) yield return null;
                r.finalStopped = !c.BodyControlActive && (body == null || !body.BodyActive);
            }
            r.elapsed = Time.realtimeSinceStartup - began;
            r.result = r.goalConfirmed && r.revealComplete && r.finalStopped && r.liveSourceMaintained
                && r.freshBrainMaintained && string.IsNullOrEmpty(r.error) ? "full_course_live_brain_clear" : "incomplete";
            File.WriteAllText(path, JsonUtility.ToJson(r, true));
            Debug.Log("FULL_COURSE_PROBE " + r.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }
        [Serializable] sealed class EnglishRouteSample
        {
            public string phase, action, executionId, source, error, protocolError;
            public float elapsed, frameAgeMs, horizontalDistance;
            public long sequence, appliedSequence;
            public int requestId, epoch, generation;
            public bool ready, rawBrainReady, freshBrain, bodyActive;
        }
        [Serializable] sealed class EnglishRouteReport
        {
            public string result = "incomplete", error, backend, language, questionCaption;
            public string brainEndpoint = "127.0.0.1:18766";
            public string ambiguousText = "Take me to the finish, please";
            public string questionText = "Why do flies have six legs?";
            public string fallbackAttribution = "Requires Bridge goal_route_fallback_started action/commandId log correlation with this probe time and applied request";
            public bool titleStarted, englishUi, legacyJapaneseRequestIgnored, noLanguageToggle, microphoneDisabled, rawBrainReady;
            public bool ambiguousApplied, ambiguousMoved, stopApplied, forwardApplied, questionKeptExecution, responseObserved, finalStopped;
            public bool liveSourceMaintained = true, freshBrainMaintained = true;
            public float elapsed, ambiguousDistance, questionDistance;
            public long questionTranscriptDeltas;
            public List<string> uiLabels = new List<string>();
            public List<EnglishRouteSample> samples = new List<EnglishRouteSample>();
        }

        IEnumerator RunEnglishRouteProbe(string path)
        {
            var r = new EnglishRouteReport();
            float began = Time.realtimeSinceStartup, finish = began + 90;
            var title = FindAnyObjectByType<Flylingual.PlayScreen.TitleScreen>();
            ConversationSessionController c = null;
            float until = Mathf.Min(finish, began + 40);
            while (Time.realtimeSinceStartup < until)
            {
                c = FindAnyObjectByType<ConversationSessionController>();
                if (title == null) title = FindAnyObjectByType<Flylingual.PlayScreen.TitleScreen>();
                if (title != null && title.CanStart && c != null) break;
                yield return null;
            }
            var demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
            var body = c == null ? null : c.GetComponent<NativeConversationBody>();
            if (title != null && title.CanStart)
            {
                title.StartGame(); yield return null;
                if (Flylingual.PlayScreen.TitleScreen.BlocksGameplay) { title.StartGame(); yield return null; }
            }
            r.titleStarted = !Flylingual.PlayScreen.TitleScreen.BlocksGameplay;
            Flylingual.PlayScreen.GameLanguage.SetLanguage("ja");
            r.legacyJapaneseRequestIgnored = Flylingual.PlayScreen.GameLanguage.Code == "en";
            r.language = c == null ? null : c.Settings.language;
            r.englishUi = Flylingual.PlayScreen.GameLanguage.Code == "en" && r.language == "en";
            r.noLanguageToggle = true;
            int documents = 0;
            foreach (var doc in FindObjectsByType<UIDocument>(FindObjectsSortMode.None))
            {
                documents++;
                var root = doc.rootVisualElement;
                r.noLanguageToggle &= root.Q("language-ja") == null && root.Q("language-en") == null;
                foreach (var field in root.Query<DropdownField>().ToList())
                    r.noLanguageToggle &= field.label != "Language" && field.label != "言語";
                foreach (var label in root.Query<TextElement>().ToList())
                {
                    if (string.IsNullOrEmpty(label.text)) continue;
                    r.uiLabels.Add(label.text);
                    r.englishUi &= !System.Text.RegularExpressions.Regex.IsMatch(label.text, "[ぁ-んァ-ヶ一-龯]");
                }
            }
            r.noLanguageToggle &= documents > 0;
            r.microphoneDisabled = c != null && c.MicrophoneCaptureDisabled;
            if (!r.titleStarted || c == null || !r.microphoneDisabled || demo == null || demo.body == null
                || demo.controller == null || demo.live == null || body == null || !c.BodyControlActive)
                r.error = "requires_ready_title_no_microphone_and_real_body";
            else
            {
                Vector3 origin = demo.body.Position;
                Action<string> sample = phase =>
                {
                    bool live = demo.controller.MotorSource == demo.live;
                    r.liveSourceMaintained &= live;
                    r.freshBrainMaintained &= c.HasFreshBrain;
                    r.samples.Add(new EnglishRouteSample { phase = phase, elapsed = Time.realtimeSinceStartup - began,
                        action = c.LastAppliedAction, executionId = c.ActiveExecution?.executionId,
                        source = live ? "LiveTcp" : "other", sequence = c.Sequence, appliedSequence = c.LastAppliedSequence,
                        requestId = c.LastAppliedRequestId, epoch = c.ControlEpoch, generation = c.ConversationGeneration,
                        ready = c.Ready, rawBrainReady = c.BrainReady, freshBrain = c.HasFreshBrain,
                        bodyActive = c.BodyControlActive && body.BodyActive, frameAgeMs = c.FrameAgeMs,
                        error = c.Error, protocolError = c.SchemaError,
                        horizontalDistance = Vector3.ProjectOnPlane(demo.body.Position - origin, Vector3.up).magnitude });
                    File.WriteAllText(path, JsonUtility.ToJson(r, true));
                };
                sample("ready");
                // Let the normal route sensor publish; no route, pose or motor is injected.
                yield return new WaitForSecondsRealtime(1);
                int applied = c.AppliedActions;
                c.SendPlayerText(r.ambiguousText);
                until = Mathf.Min(finish - 5, Time.realtimeSinceStartup + 18);
                float nextSample = 0;
                while (Time.realtimeSinceStartup < until && c.BodyControlActive)
                {
                    r.ambiguousApplied |= c.AppliedActions > applied && c.LastAppliedAction != "STOP"
                        && c.LastAppliedSequence > 0 && body.TcpSequence >= c.LastAppliedSequence;
                    r.ambiguousDistance = Vector3.ProjectOnPlane(demo.body.Position - origin, Vector3.up).magnitude;
                    r.ambiguousMoved = r.ambiguousApplied && r.ambiguousDistance > .001f;
                    if (Time.realtimeSinceStartup >= nextSample) { sample("ambiguous"); nextSample = Time.realtimeSinceStartup + .25f; }
                    if (r.ambiguousMoved) break;
                    yield return null;
                }
                sample("ambiguous_end");
                applied = c.AppliedActions;
                c.SendPlayerText("Stop");
                until = Mathf.Min(finish - 5, Time.realtimeSinceStartup + 8);
                while (Time.realtimeSinceStartup < until && c.BodyControlActive)
                {
                    r.stopApplied = c.AppliedActions > applied && c.LastAppliedAction == "STOP"
                        && c.LastAppliedSequence > 0 && body.TcpSequence >= c.LastAppliedSequence;
                    if (r.stopApplied) break;
                    yield return null;
                }
                sample("stop");
                if (r.stopApplied && Time.realtimeSinceStartup < finish - 15)
                {
                    applied = c.AppliedActions;
                    c.SendPlayerText("Move forward for 8 seconds");
                    until = Mathf.Min(finish - 8, Time.realtimeSinceStartup + 10);
                    while (Time.realtimeSinceStartup < until && c.BodyControlActive)
                    {
                        r.forwardApplied = c.AppliedActions > applied && c.LastAppliedAction == "FORWARD"
                            && c.LastAppliedSequence > 0 && body.TcpSequence >= c.LastAppliedSequence
                            && c.ActiveExecution != null && c.ActiveExecution.action == "FORWARD";
                        if (r.forwardApplied) break;
                        yield return null;
                    }
                    sample("forward");
                    if (r.forwardApplied)
                    {
                        string execution = c.ActiveExecution.executionId;
                        int epoch = c.ControlEpoch, generation = c.ConversationGeneration;
                        long deltas = c.ReceivedAssistantTranscriptDeltas;
                        Vector3 questionOrigin = demo.body.Position;
                        c.SendPlayerText(r.questionText);
                        r.questionKeptExecution = true;
                        until = Mathf.Min(finish - 3, Time.realtimeSinceStartup + 3);
                        nextSample = 0;
                        while (Time.realtimeSinceStartup < until)
                        {
                            r.questionKeptExecution &= c.BodyControlActive && c.ControlEpoch == epoch
                                && c.ConversationGeneration == generation && c.ActiveExecution != null
                                && c.ActiveExecution.executionId == execution && c.ActiveExecution.action == "FORWARD";
                            if (Time.realtimeSinceStartup >= nextSample) { sample("question"); nextSample = Time.realtimeSinceStartup + .25f; }
                            yield return null;
                        }
                        r.questionDistance = Vector3.ProjectOnPlane(demo.body.Position - questionOrigin, Vector3.up).magnitude;
                        until = Mathf.Min(finish - 3, Time.realtimeSinceStartup + 5);
                        while (Time.realtimeSinceStartup < until && c.ReceivedAssistantTranscriptDeltas <= deltas) yield return null;
                        r.questionTranscriptDeltas = c.ReceivedAssistantTranscriptDeltas - deltas;
                        r.questionCaption = c.Caption;
                        r.responseObserved = r.questionTranscriptDeltas > 0;
                        sample("question_end");
                    }
                }
                r.backend = c.Backend; r.rawBrainReady = c.BrainReady;
                if (string.IsNullOrEmpty(r.error)) r.error = c.Error ?? c.SchemaError;
            }
            if (c != null)
            {
                c.EmergencyStop();
                until = Mathf.Min(finish, Time.realtimeSinceStartup + 3);
                while (Time.realtimeSinceStartup < until && (c.BodyControlActive || c.ConversationActive)) yield return null;
                r.finalStopped = !c.BodyControlActive && (body == null || !body.BodyActive);
            }
            r.elapsed = Time.realtimeSinceStartup - began;
            r.result = r.titleStarted && r.englishUi && r.legacyJapaneseRequestIgnored && r.noLanguageToggle && r.ambiguousMoved && r.stopApplied
                && r.forwardApplied && r.questionKeptExecution && r.questionDistance > .001f && r.responseObserved
                && r.finalStopped && r.liveSourceMaintained && r.freshBrainMaintained && string.IsNullOrEmpty(r.error)
                ? "english_route_behavior_pass_pending_bridge_attribution" : "incomplete";
            File.WriteAllText(path, JsonUtility.ToJson(r, true));
            Debug.Log("ENGLISH_ROUTE_PROBE " + r.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }
        [Serializable] sealed class TitleConnectionReport
        {
            public string result = "incomplete", error, backend, status;
            public bool earlyStartBlocked, readyBehindTitle, pausedBehindTitle = true, timersZeroBehindTitle = true;
            public bool noMicrophoneBeforeStart = true, bodyStationary = true, languageReconnected, started, stopped;
            public bool rawBrainReady, freshBrain, noEarlyStrike;
            public long sequenceBefore, sequenceAfter;
            public float gameplayElapsed, idleElapsed;
        }

        IEnumerator RunTitleConnectionProbe(string path, Flylingual.PlayScreen.TitleScreen title)
        {
            var report = new TitleConnectionReport();
            var swatter = FindAnyObjectByType<Flylingual.BlindSugarRun.BlindSugarRunIdleSwatter>();
            var demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
            string originalLanguage = Flylingual.PlayScreen.GameLanguage.Code;
            Vector3 origin = demo == null ? Vector3.zero : demo.body.Position;
            ConversationSessionController controller = null;
            if (title != null)
            {
                title.StartGame();
                report.earlyStartBlocked = Flylingual.PlayScreen.TitleScreen.BlocksGameplay && !title.CanStart;
                float until = Time.realtimeSinceStartup + 100;
                while (Time.realtimeSinceStartup < until)
                {
                    controller = FindAnyObjectByType<ConversationSessionController>();
                    if (swatter == null) swatter = FindAnyObjectByType<Flylingual.BlindSugarRun.BlindSugarRunIdleSwatter>();
                    report.pausedBehindTitle &= Time.timeScale == 0f;
                    report.timersZeroBehindTitle &= swatter == null || (swatter.GameplayElapsed == 0f && swatter.IdleElapsed == 0f && !swatter.Counting);
                    report.noMicrophoneBeforeStart &= controller == null || (!controller.MicrophoneCapturing && controller.SentAudioChunks == 0);
                    report.bodyStationary &= demo == null || Vector3.Distance(origin, demo.body.Position) < .001f;
                    if (title.CanStart) break;
                    yield return null;
                }
                report.readyBehindTitle = title.CanStart && Flylingual.PlayScreen.TitleScreen.BlocksGameplay;
                report.status = title.ConnectionMessage;
                if (report.readyBehindTitle && controller != null)
                {
                    if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyTitleLanguageProbe") >= 0)
                    {
                        string nextLanguage = originalLanguage == "ja" ? "en" : "ja";
                        Flylingual.PlayScreen.GameLanguage.SetLanguage(nextLanguage);
                        title.StartGame();
                        bool blocked = Flylingual.PlayScreen.TitleScreen.BlocksGameplay && !title.CanStart;
                        until = Time.realtimeSinceStartup + 90;
                        while (!title.CanStart && Time.realtimeSinceStartup < until) yield return null;
                        report.languageReconnected = blocked && title.CanStart && controller.Settings.language == nextLanguage;
                    }
                    else report.languageReconnected = true;
                    report.sequenceBefore = controller.Sequence;
                    yield return new WaitForSecondsRealtime(3);
                    report.pausedBehindTitle &= Time.timeScale == 0;
                    report.timersZeroBehindTitle &= swatter != null && swatter.GameplayElapsed == 0 && swatter.IdleElapsed == 0 && !swatter.Counting;
                    report.noMicrophoneBeforeStart &= !controller.MicrophoneCapturing && controller.SentAudioChunks == 0;
                    report.bodyStationary &= demo == null || Vector3.Distance(origin, demo.body.Position) < .001f;
                    title.StartGame(); yield return null;
                    if (Flylingual.PlayScreen.TitleScreen.BlocksGameplay) { title.StartGame(); yield return null; }
                    report.started = !Flylingual.PlayScreen.TitleScreen.BlocksGameplay;
                    until = Time.realtimeSinceStartup + 4;
                    while (Time.realtimeSinceStartup < until) yield return null;
                    report.gameplayElapsed = swatter == null ? -1 : swatter.GameplayElapsed;
                    report.idleElapsed = swatter == null ? -1 : swatter.IdleElapsed;
                    report.noEarlyStrike = swatter != null && !swatter.Struck && !swatter.WarningActive;
                    report.sequenceAfter = controller.Sequence;
                    report.backend = controller.Backend;
                    report.rawBrainReady = controller.BrainReady;
                    report.freshBrain = controller.HasFreshBrain;
                    report.error = controller.Error;
                    controller.StopConversation();
                    yield return new WaitForSecondsRealtime(3);
                    report.stopped = !controller.IsSessionRequested && !controller.ConversationLive;
                }
            }
            report.result = report.earlyStartBlocked && report.readyBehindTitle && report.pausedBehindTitle
                && report.timersZeroBehindTitle && report.noMicrophoneBeforeStart && report.bodyStationary
                && report.languageReconnected && report.started && report.noEarlyStrike && report.freshBrain
                && report.sequenceAfter > report.sequenceBefore && report.gameplayElapsed > 0 && report.gameplayElapsed < 6
                && report.stopped && string.IsNullOrEmpty(report.error) ? "title_connection_gate_pass" : "incomplete";
            Flylingual.PlayScreen.GameLanguage.SetLanguage(originalLanguage);
            File.WriteAllText(path, JsonUtility.ToJson(report, true));
            Debug.Log("TITLE_CONNECTION_PROBE " + report.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }

        [Serializable] sealed class AssistReport
        {
            public string result = "incomplete", error, backend;
            public bool liveSource, farUnchanged, nearSteering, stopUnchanged, flagOffUnchanged, expandedClear, revealComplete;
            public bool controlledGoalFixture = true, rawBrainReady, freshBrain;
            public long firstSequence, lastSequence;
            public float startDisplacement, peakAssist, peakTurnCorrection;
        }

        IEnumerator RunDemoAssistProbe(string path, ConversationSessionController controller)
        {
            var r = new AssistReport();
            var demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
            var assist = FindAnyObjectByType<Flylingual.BlindSugarRun.FlyDemoSafetyAssist>();
            var goal = FindAnyObjectByType<Flylingual.BlindSugarRun.BlindSugarRunGoal>();
            var stage = FindAnyObjectByType<Flylingual.BlindSugarRun.BlindSugarRunSession>();
            if (controller != null && controller.MicrophoneCaptureDisabled && assist != null && goal != null
                && goal.GoalVolume != null && demo != null && stage != null && controller.BodyControlActive)
            {
                r.firstSequence = controller.Sequence;
                Vector3 origin = demo.body.Position;
                Vector3 originalGoal = goal.GoalVolume.transform.position;
                bool originalGoalEnabled = goal.enabled;
                // Bounded fixture only: move the trigger, never the fly or its motor source.
                // This validates contact logic, not traversal of the actual course.
                goal.enabled = false;
                int applied = controller.AppliedActions;
                controller.SendPlayerText("8秒間前に進んで");
                float until = Time.realtimeSinceStartup + 10;
                while (controller.AppliedActions == applied && Time.realtimeSinceStartup < until) yield return null;
                yield return new WaitForSecondsRealtime(2);
                r.farUnchanged = controller.LastAppliedAction == "FORWARD" && assist.DistanceToGoal > 3
                    && assist.CurrentAssist == 0 && assist.RawMotor.forward == assist.AssistedMotor.forward
                    && assist.RawMotor.turn == assist.AssistedMotor.turn;
                r.startDisplacement = Vector3.ProjectOnPlane(demo.body.Position - origin, Vector3.up).magnitude;
                goal.GoalVolume.transform.position += demo.body.Position + demo.body.Thorax.transform.forward * 1.5f
                    + demo.body.Thorax.transform.right - goal.GoalVolume.bounds.center;
                until = Time.realtimeSinceStartup + 2;
                while (Time.realtimeSinceStartup < until)
                {
                    r.peakAssist = Mathf.Max(r.peakAssist, assist.CurrentAssist);
                    r.peakTurnCorrection = Mathf.Max(r.peakTurnCorrection, Mathf.Abs(assist.RawMotor.turn - assist.AssistedMotor.turn));
                    yield return null;
                }
                r.nearSteering = r.peakAssist > 0 && r.peakAssist <= .65f && r.peakTurnCorrection > .001f;
                assist.enableDemoSafetyAssist = false;
                yield return new WaitForSecondsRealtime(.2f);
                r.flagOffUnchanged = assist.CurrentAssist == 0 && assist.RawMotor.forward == assist.AssistedMotor.forward
                    && assist.RawMotor.turn == assist.AssistedMotor.turn;
                assist.enableDemoSafetyAssist = true;
                controller.SendPlayerText("止まって");
                until = Time.realtimeSinceStartup + 8;
                while ((controller.ActiveExecution != null || controller.LastAppliedAction != "STOP")
                    && Time.realtimeSinceStartup < until) yield return null;
                yield return new WaitForSecondsRealtime(.2f);
                r.stopUnchanged = controller.LastAppliedAction == "STOP" && assist.CurrentAssist == 0
                    && assist.RawMotor.turn == assist.AssistedMotor.turn;
                r.liveSource = demo.controller.MotorSource == demo.live;
                r.lastSequence = controller.Sequence; r.backend = controller.Backend;
                r.rawBrainReady = controller.BrainReady; r.freshBrain = controller.HasFreshBrain;
                r.error = controller.Error;
                // Place the fly 0.4m outside the original horizontal trigger edge.
                Vector3 center = demo.body.Position + Vector3.right * (goal.GoalVolume.bounds.extents.x + .4f);
                goal.GoalVolume.transform.position += center - goal.GoalVolume.bounds.center;
                goal.enabled = true;
                until = Time.realtimeSinceStartup + 3;
                while (stage.State == Flylingual.BlindSugarRun.BlindSugarRunSession.StageState.Playing
                    && Time.realtimeSinceStartup < until) yield return null;
                r.expandedClear = stage.State == Flylingual.BlindSugarRun.BlindSugarRunSession.StageState.Goal
                    || stage.State == Flylingual.BlindSugarRun.BlindSugarRunSession.StageState.Reveal;
                var reveal = stage.GetComponent<Flylingual.BlindSugarRun.BlindSugarRunReveal>();
                until = Time.realtimeSinceStartup + 10;
                while (reveal != null && !reveal.Complete && Time.realtimeSinceStartup < until) yield return null;
                r.revealComplete = reveal != null && reveal.Complete;
                ScreenCapture.CaptureScreenshot(Path.ChangeExtension(path, ".png"));
                yield return null;
                goal.GoalVolume.transform.position = originalGoal;
                goal.enabled = originalGoalEnabled;
                controller.StopConversation();
                r.result = r.liveSource && r.farUnchanged && r.startDisplacement > .001f && r.nearSteering
                    && r.stopUnchanged && r.flagOffUnchanged && r.expandedClear && r.revealComplete && r.freshBrain
                    && r.lastSequence > r.firstSequence && string.IsNullOrEmpty(r.error)
                    ? "demo_assist_limited_pass" : "incomplete";
            }
            File.WriteAllText(path, JsonUtility.ToJson(r, true));
            Debug.Log("DEMO_ASSIST_PROBE " + r.result);
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
