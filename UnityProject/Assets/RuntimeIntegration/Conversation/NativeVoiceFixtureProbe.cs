using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using FlyBrainPoC;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Opt-in synthetic PCM input; all interpretation, neural output and physics remain real.</summary>
    [DefaultExecutionOrder(-10000)]
    public sealed class NativeVoiceFixtureProbe : MonoBehaviour
    {
        [Serializable] sealed class Manifest { public int schemaVersion; public Fixture[] fixtures; }
        [Serializable] sealed class Fixture
        {
            public string id, file, sha256, expectedAction, utterance, expectedKind, expectedPlan;
            public double durationSeconds;
            [NonSerialized] public VoiceFixtureClip clip;
            [NonSerialized] public AudioClip monitorClip;
        }
        [Serializable] sealed class Control
        {
            public string type, @event, stage, commandId, delegationId, inputId, fixtureId, action, source, kind, interpretRoute;
            public string plan, planId, name, outcome, reason, state, owner, sessionId, instanceId;
            public int epoch, conversationGeneration, requestId, fixtureChunkIndex, step, transcriptChars;
            public long sequence;
            public double monotonicMs, audioStartMs, audioEndMs, startMs, endMs, offsetMs;
            public double interpretationMs, proposalValidForMs, intentAgeMs, executionDurationMs;
            public double speechEndMonotonicMs;
            public bool utteranceFinalized;
            public bool continuedListening, outputInhibited;
            public ActiveExecution activeExecution;
            [NonSerialized] public double localTime;
            [NonSerialized] public int observedGeneration;
            [NonSerialized] public string observedSessionId, observedInstanceId;
        }
        [Serializable] sealed class ActiveExecution
        {
            public string executionId, action, plan, executionMode;
            public int step, requestId;
            public double remainingMs;
            public bool monitorHazards;
        }
        [Serializable] sealed class InputTranscript
        {
            public string role, text;
            public bool append;
            public int conversationGeneration = -1;
        }
        [Serializable] sealed class UpstreamFrame
        {
            public int sequence, appliedRequestId;
            public BackendMetadata metadata;
        }
        [Serializable] sealed class Motion
        {
            public bool matchedAppliedFrame, grounded;
            public int upstreamRequestId, tcpAppliedRequestId, firstSequence, samples;
            public double startedAt;
            public Vector3 startPosition, endPosition;
            public float horizontalDisplacement, forwardDisplacement, forwardTravel, yawDegrees, phaseTravel;
            public float currentForwardPeak, currentTurnPeak, actualForwardPeak, actualTurnPeak;
            public string matchRule = "Original control-WS requestId/sequence + same-session motor-TCP sequence/action; GPT TCP requestId is mapped to zero";
            [NonSerialized] public Vector3 previousPosition, initialForward;
            [NonSerialized] public float previousYaw, previousPhase;
        }
        [Serializable] sealed class Case
        {
            public string id, fixtureId, fixtureHash, expectedKind, expectedAction, expectedPlan;
            public string actualKind, actualAction, actualPlan, commandId, delegationId, inputId, intentSource, planId;
            public string status = "pending", error, correlation = "unconfirmed";
            public int epoch, generation, requestId, sentChunks, observedSamples;
            public long appliedSequence, sourceSampleStart, sourceSampleEnd;
            public double startedAt, firstAudioAt = -1, lastAudioAt = -1, appliedAt = -1, endedAt;
            public double bridgeAudioStartMs = -1, bridgeAudioEndMs = -1;
            public double durationSeconds;
            public int sourceSampleRate, sourceChannels;
            public double delegationStartMs, delegationEndMs, delegationOffsetMs;
            public double inputStartMs, inputEndMs, inputOffsetMs;
            public double fixtureToAppliedMs, fixtureToBodyStartedMs, fixtureToSettledMs;
            public double audioEndToAppliedMs = -1, audioEndToBodyStartedMs = -1;
            public string interpretRoute;
            public double acceptedExecutionDurationMs, submittedToExpiryMs;
            public bool applied, bodyStarted, settled, expired, continuedListening, voiceStopBeforeExpiry, executionUpdated;
            public bool replyStarted, replyCompleted;
            public bool recognizedMatchesFixture;
            public int recognizedCharacterCount;
            public string diagnosticTranscript;
            public int freshFrameAdvances;
            [NonSerialized] public long lastFreshSequence;
            public string executionId, executionMode;
            public bool replyOverlap, replyOverlapRequested, sourceMaintained = true, freshMaintained = true;
            public bool sameEpoch = true, sameSession = true, grounded;
            public string brainSessionId, brainInstanceId;
            public float horizontalDisplacement, forwardDisplacement, forwardTravel, yawDegrees, phaseTravel;
            public float currentForwardPeak, currentTurnPeak, actualForwardPeak, actualTurnPeak, frameAgeMax;
            public Vector3 startPosition, endPosition;
            public Motion postAppliedMotion = new Motion();
            public List<Control> lifecycle = new List<Control>();
            [NonSerialized] public Vector3 previousPosition, initialForward;
            [NonSerialized] public float previousYaw, previousPhase;
            [NonSerialized] public long replySamplesAtStart;
            [NonSerialized] public StringBuilder recognizedText = new StringBuilder();
            [NonSerialized] public bool recognizedTextOverflow;
        }
        [Serializable] sealed class Report
        {
            public string result = "incomplete", status = "incomplete", suite, inputSource = "synthetic_fixture";
            public string manifest, manifestSha256, error, backend, brainSessionId, brainInstanceId;
            public bool pass, brainReady, microphoneTested, startupFreshStop, overlapVerified;
            public bool scriptCueAccepted, scriptOverlapAtFirstChunk, scriptStopMaintained;
            public double scriptCueSentAt = -1, scriptCueAcceptedAt = -1, scriptAudioStartedAt = -1;
            public double scriptDiscardReceivedAt = -1, scriptInterruptDiagnosticAt = -1;
            public long scriptSamplesBefore, scriptSamplesAtStart;
            public int scriptNarratorsDisabled;
            public bool persistentHeld, persistentContinued, persistentStopped, persistentFiniteExpired, persistentNoRevival;
            public bool stopped, controllerReleasedObserved, bridgeStoppedObserved, protocolShutdownObserved, processCleanupObserved;
            public int ttlReacceptChecks, physicsResetCount;
            public long sentFixtureAudioChunks, sentPcmSamples;
            public double startedAt, endedAt, requestedSeconds, minSendIntervalMs, maxSendIntervalMs;
            public double persistentObservationSeconds;
            public bool monitorFixtures;
            public string timing = "Unity realtime clock; Bridge monotonic clock recorded separately";
            public string limitation = "Synthetic PCM is not a physical microphone test. Process cleanup belongs to the runner.";
            public List<Case> cases = new List<Case>();
        }
        [Serializable] sealed class Observation
        {
            public double realtimeSeconds;
            public string caseId, inputSource, sessionId, instanceId, backend, error;
            public int epoch, generation, sequence;
            public bool live, bodyActive, sourceEqualsLive, fixtureTransmitting, microphoneCapturing, replyPlaying, ready;
            public long sentFixtureChunks, playedNonzeroSamples;
            public float ageSeconds, actualForward, actualTurn, currentForward, currentTurn, yawDegrees, brainStepWallMs;
            public Vector3 position, velocity;
        }
        [Serializable] sealed class Entry
        {
            public string @event, caseId, fixtureId, detail;
            public double realtimeSeconds;
            public int epoch, generation, chunkIndex;
            public long sampleCursor;
            public Control control;
        }
        sealed class PhysicsBaseline
        {
            public Vector3 position;
            public Quaternion rotation;
            public List<float> joints;
            public float phase;
        }

        readonly Dictionary<string, Fixture> fixtures = new Dictionary<string, Fixture>(StringComparer.Ordinal);
        readonly List<Control> controls = new List<Control>();
        readonly Dictionary<string, Control> delegations = new Dictionary<string, Control>();
        readonly Dictionary<string, Control> transcriptCandidates = new Dictionary<string, Control>();
        readonly Dictionary<int, UpstreamFrame> appliedFrames = new Dictionary<int, UpstreamFrame>();
        readonly byte[] silence = new byte[4800];
        ConversationSessionController controller;
        NativeConversationBody body;
        FlyVisualDemo.WindowsReplayDemo demo;
        Report report;
        PhysicsBaseline baseline;
        StreamWriter events, observations;
        string outputDirectory;
        Case current;
        Fixture playing;
        int chunkIndex, audioEpoch, audioGeneration;
        long sampleCursor;
        double nextAudioAt, audioNotBefore, previousAudioAt = -1, nextObservationAt, deadline;
        bool running, quit, observationEnabled, textDiagnosticsEnabled, monitorFixtures;
        bool scriptProducerConflict;
        string recordingGatePath;
        double recordingStartedAt = -1;
        ActiveExecution activeExecution;
        GameObject monitorObject;
        AudioSource monitorSource;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyCourseProbe") >= 0) return;
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyVoiceFixtures") < 0) return;
            new GameObject("Native synthetic voice fixture probe").AddComponent<NativeVoiceFixtureProbe>();
        }

        IEnumerator Start()
        {
            if (!Initialize()) { if (quit) Application.Quit(); yield break; }
            double startupDeadline = Now + 80;
            while (Now < startupDeadline)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                body = FindAnyObjectByType<NativeConversationBody>();
                demo = FindAnyObjectByType<FlyVisualDemo.WindowsReplayDemo>();
                if (controller != null && controller.Ready && body != null && demo != null && demo.body != null) break;
                yield return null;
            }
            if (controller == null || !controller.Ready || body == null || demo == null || demo.body == null)
            { yield return FinishRun("startup_unavailable"); yield break; }
            if (!string.IsNullOrEmpty(recordingGatePath))
            {
                File.WriteAllText(Path.Combine(outputDirectory, "recording-ready.txt"), "ready\n", new UTF8Encoding(false));
                Log("recording_gate_ready", null);
                double gateDeadline = Now + 300;
                while (!File.Exists(recordingGatePath) && Now < gateDeadline) yield return null;
                if (!File.Exists(recordingGatePath)) { yield return FinishRun("recording_gate_timeout"); yield break; }
                recordingStartedAt = Now;
                deadline = Now + report.requestedSeconds;
                startupDeadline = Now + 80;
                Log("recording_gate_opened", null);
            }
            if (report.suite == "english-demo" || report.suite == "english-chat-demo")
            {
                bool titleStarted = false;
                yield return EnterEnglishDemoGameplay(value => titleStarted = value);
                if (!titleStarted) { yield return FinishRunAfterRecording("title_screen_blocked"); yield break; }
            }
            controller.ControlEventReceived += OnControl;
            observationEnabled = controller.EnableVoiceTestObservation();
            if (!controller.FixtureInputEnabled || !observationEnabled)
            { yield return FinishRunAfterRecording("fixture_observation_unavailable"); yield break; }
            running = true;
            nextAudioAt = Now;
            while (Now < startupDeadline && !CanObserve()) yield return null;
            if (!CanObserve()) { yield return FinishRunAfterRecording("fresh_live_control_unavailable"); yield break; }
            report.backend = controller.Backend;
            report.brainReady = controller.BrainReady;
            report.brainSessionId = controller.BrainSessionId;
            report.brainInstanceId = controller.BrainInstanceId;
            bool initialStop = false;
            yield return WaitStopped(20, value => initialStop = value);
            report.startupFreshStop = initialStop;
            if (!initialStop) { yield return FinishRunAfterRecording("startup_stop_not_observed"); yield break; }
            CaptureBaseline();

            if (report.suite == "script_interrupt") yield return RunScriptInterrupt();
            else if (report.suite == "plans") yield return RunPlans();
            else if (report.suite == "duration") yield return RunDuration();
            else if (report.suite == "persistent") yield return RunPersistent();
            else if (report.suite == "handoff") yield return RunPersistent(3);
            else if (report.suite == "english-demo") yield return RunEnglishDemo();
            else if (report.suite == "english-chat-demo") yield return RunEnglishChatDemo();
            else
            {
                yield return RunSmoke();
                if (string.IsNullOrEmpty(report.error) && report.suite == "full") yield return RunFull();
                if (string.IsNullOrEmpty(report.error) && report.suite == "soak")
                {
                    int cycle = 0;
                    while (Now + 25 < deadline && string.IsNullOrEmpty(report.error))
                    {
                        yield return RunExpiryCase((cycle++ % 2 == 0) ? "ambiguous_forward" : "ambiguous_right", false);
                    }
                    while (Now < deadline && string.IsNullOrEmpty(report.error))
                    {
                        if (current == null || !Healthy(current))
                        { report.error = "soak_waiting_control_session_or_freshness_lost"; break; }
                        yield return null;
                    }
                }
            }
            yield return FinishRunAfterRecording(report.error);
        }

        IEnumerator FinishRun(string error)
        {
            Finish(error);
            // Explicit test termination uses the normal public session stop. No text or motor injection.
            if (controller != null) controller.StopConversation();
            double cleanupDeadline = Now + 4;
            while (controller != null && Now < cleanupDeadline && (controller.ConversationLive || controller.FixtureInputTransmitting)) yield return null;
            report.stopped = controller != null && !controller.ConversationLive && !controller.FixtureInputTransmitting;
            if (!report.stopped)
            {
                report.pass = false; report.status = "incomplete"; report.result = "incomplete";
                report.error = string.IsNullOrEmpty(report.error) ? "session_stop_not_confirmed" : report.error + ";session_stop_not_confirmed";
            }
            Save();
            Close();
            if (quit) Application.Quit();
        }

        IEnumerator FinishRunAfterRecording(string error)
        {
            yield return HoldRecordingMinimum();
            yield return FinishRun(error);
        }

        bool Initialize()
        {
            quit = Array.IndexOf(Environment.GetCommandLineArgs(), "-flyVoiceFixtureQuit") >= 0;
            textDiagnosticsEnabled = Array.IndexOf(Environment.GetCommandLineArgs(), "-flyVoiceFixtureTextDiagnostics") >= 0;
            monitorFixtures = Array.IndexOf(Environment.GetCommandLineArgs(), "-flyVoiceFixtureMonitor") >= 0;
            recordingGatePath = Argument("-flyVoiceRecordingGate");
            try
            {
                string path = Path.GetFullPath(Argument("-flyVoiceFixtures"));
                outputDirectory = Argument("-flyVoiceFixtureOutput");
                if (string.IsNullOrWhiteSpace(outputDirectory)) throw new ArgumentException("output_directory_required");
                outputDirectory = Path.GetFullPath(outputDirectory);
                Directory.CreateDirectory(outputDirectory);
                if (File.Exists(Path.Combine(outputDirectory, "report.json"))) throw new ArgumentException("output_already_contains_report");
                string suite = Argument("-flyVoiceFixtureSuite") ?? "smoke";
                if (suite != "smoke" && suite != "full" && suite != "soak" && suite != "plans" && suite != "duration" && suite != "persistent" && suite != "handoff" && suite != "script_interrupt" && suite != "english-demo" && suite != "english-chat-demo") throw new ArgumentException("invalid_suite");
                if (!string.IsNullOrEmpty(recordingGatePath) && suite != "english-demo" && suite != "english-chat-demo") throw new ArgumentException("recording_gate_requires_english_suite");
                if (!string.IsNullOrEmpty(recordingGatePath)) recordingGatePath = Path.GetFullPath(recordingGatePath);
                double seconds = suite == "full" ? 900 : suite == "soak" ? 300 : suite == "duration" ? 180 : suite == "persistent" ? 180 : (suite == "handoff" || suite == "script_interrupt" || suite == "english-demo" || suite == "english-chat-demo") ? 120 : 240;
                string duration = Argument("-flyVoiceFixtureSeconds");
                if (duration != null && (!double.TryParse(duration, NumberStyles.Float, CultureInfo.InvariantCulture, out seconds)
                    || double.IsNaN(seconds) || double.IsInfinity(seconds) || seconds < 1 || seconds > 3600)) throw new ArgumentException("invalid_duration");
                if (suite == "persistent" && seconds < 120) throw new ArgumentException("persistent_duration_too_short");
                report = new Report { suite = suite, manifest = path, startedAt = Now, requestedSeconds = seconds, monitorFixtures = monitorFixtures };
                if (suite == "handoff") report.limitation += " Short audio handoff diagnostic with a 3-second initial hold; not evidence for the 60-second persistent gate.";
                if (suite == "english-demo") report.limitation += " English demo verifies four bounded action/STOP fixtures; the optional nudge plan remains outside this initial action smoke.";
                if (suite == "english-chat-demo") report.limitation += " Question cases prove transcript candidate timing and reply playback, not a provider response ID or semantic answer quality.";
                using (var sha = SHA256.Create()) report.manifestSha256 = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-", "").ToLowerInvariant();
                deadline = Now + seconds;
                events = Writer("events.jsonl"); observations = Writer("observations.jsonl");
                Manifest manifest = JsonUtility.FromJson<Manifest>(File.ReadAllText(path));
                if (manifest == null || (manifest.schemaVersion != 1 && manifest.schemaVersion != 2) || manifest.fixtures == null || manifest.fixtures.Length == 0)
                    throw new ArgumentException("invalid_manifest");
                string directory = Path.GetDirectoryName(path);
                foreach (Fixture fixture in manifest.fixtures)
                {
                    if (fixture == null || !SafeId(fixture.id) || string.IsNullOrWhiteSpace(fixture.file) || fixtures.ContainsKey(fixture.id))
                        throw new ArgumentException("invalid_fixture_entry");
                    string resolved = Path.GetFullPath(Path.Combine(directory, fixture.file));
                    if (!resolved.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                        throw new ArgumentException("fixture_path_outside_manifest_directory");
                    fixture.clip = VoiceFixtureClip.Load(resolved, fixture.sha256);
                    if (fixture.clip.Chunks == null || fixture.clip.Chunks.Length == 0) throw new ArgumentException("empty_fixture");
                    if (fixture.expectedKind == null) fixture.expectedKind = "action";
                    if (fixture.expectedKind != "action" && fixture.expectedKind != "plan" && fixture.expectedKind != "update" && fixture.expectedKind != "question") throw new ArgumentException("invalid_expected_kind");
                    if (fixture.expectedKind == "action" && !IsAction(fixture.expectedAction)) throw new ArgumentException("invalid_expected_action");
                    if (fixture.expectedKind == "plan" && !IsPlan(fixture.expectedPlan)) throw new ArgumentException("invalid_expected_plan");
                    if (fixture.expectedKind == "update" && !IsAction(fixture.expectedAction)) throw new ArgumentException("invalid_expected_action");
                    fixtures.Add(fixture.id, fixture);
                }
                string[] required = suite == "script_interrupt" ? new[] { "stop" } : suite == "plans" ? Array.Empty<string>() : (suite == "persistent" || suite == "handoff")
                    ? new[] { "persistent_forward", "persistent_continue", "persistent_conditions", "stop", "forward8" } : suite == "duration"
                    ? new[] { "forward_default", "right_default", "left_default" } : suite == "english-chat-demo"
                    ? new[] { "02_continue", "10_mood", "11_hungry", "07_stop", "12_fly_life", "05_resume" } : suite == "english-demo"
                    ? new[] { "02_continue", "07_stop", "05_resume" } : suite == "full"
                    ? new[] { "stop", "forward8", "right8", "ambiguous_forward", "ambiguous_right", "left8", "forward_right8", "forward_left8" }
                    : new[] { "stop", "forward8", "right8", "ambiguous_forward", "ambiguous_right" };
                foreach (string id in required) if (!fixtures.ContainsKey(id)) throw new ArgumentException("required_fixture_missing");
                if (suite == "plans" && !new List<Fixture>(fixtures.Values).Exists(x => x.expectedKind == "plan")) throw new ArgumentException("plan_fixture_missing");
                Save();
                return true;
            }
            catch (Exception exception)
            {
                if (report != null) { report.error = "fixture_initialization_" + exception.GetType().Name; Save(); }
                Debug.LogError("VOICE_FIXTURE_INITIALIZATION_FAILED " + exception.GetType().Name);
                Close();
                return false;
            }
        }

        void SilenceScriptProducer()
        {
            if (Argument("-flyVoiceFixtureSuite") != "script_interrupt") return;
            foreach (var narrator in FindObjectsByType<Flylingual.BlindSugarRun.BlindSugarRunNarrator>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (narrator.SentCues > 0) scriptProducerConflict = true;
                if (!narrator.enabled) continue;
                narrator.enabled = false;
                if (report != null) report.scriptNarratorsDisabled++;
            }
        }

        IEnumerator EnterEnglishDemoGameplay(Action<bool> done)
        {
            int presses = 0;
            double until = Math.Min(deadline, Now + 20);
            while (Flylingual.PlayScreen.TitleScreen.BlocksGameplay && Now < until)
            {
                if (presses < 2)
                {
                    var title = FindAnyObjectByType<Flylingual.PlayScreen.TitleScreen>();
                    if (title != null && title.CanStart) { title.StartGame(); presses++; }
                }
                yield return null;
            }
            done(!Flylingual.PlayScreen.TitleScreen.BlocksGameplay);
        }

        IEnumerator HoldRecordingMinimum()
        {
            if (recordingStartedAt < 0) yield break;
            double recordingUntil = recordingStartedAt + 60;
            while (Now < recordingUntil) yield return null;
        }

        IEnumerator RunScriptInterrupt()
        {
            SilenceScriptProducer();
            if (scriptProducerConflict) { report.error = "script_producer_already_sent"; yield break; }
            report.limitation += " Script suite disables the scene narrator only. Audio has no public response ID: intro acknowledgement plus new nonzero playback establishes temporal overlap, not response-ID provenance; script resumption is not verified.";
            double quiet = -1, until = Math.Min(deadline, Now + 15);
            while (Now < until && CanObserve())
            {
                if (!controller.ReplyPlaying) { if (quiet < 0) quiet = Now; if (Now - quiet >= 1) break; }
                else quiet = -1;
                yield return null;
            }
            if (quiet < 0 || Now - quiet < 1 || !CanObserve()) { report.error = "script_initial_audio_not_quiet"; yield break; }
            report.scriptSamplesBefore = controller.PlayedNonzeroSamples;
            report.scriptCueSentAt = Now;
            if (!controller.TrySendBlindRunCue(Guid.NewGuid().ToString("N"), 1, 1, "intro", "{\"stageStarted\":true}", 0))
            { report.error = "script_intro_not_sent"; yield break; }
            Log("script_intro_sent", null);
            until = Math.Min(deadline, Now + 25);
            while (Now < until && CanObserve() && !(report.scriptCueAccepted && controller.ReplyPlaying
                   && controller.PlayedNonzeroSamples > report.scriptSamplesBefore)) yield return null;
            if (!report.scriptCueAccepted || !controller.ReplyPlaying || controller.PlayedNonzeroSamples <= report.scriptSamplesBefore)
            { report.error = "script_audio_overlap_unavailable"; yield break; }
            report.scriptAudioStartedAt = Now;
            report.scriptSamplesAtStart = controller.PlayedNonzeroSamples;
            Log("script_audio_observed", null);
            Case stop = Begin("stop");
            if (stop == null) yield break;
            stop.replyOverlapRequested = true;
            yield return AwaitApplied(stop, 20);
            bool settled = false;
            if (stop.applied) yield return WaitStopped(15, value => settled = value, stop.appliedSequence, stop.requestId);
            stop.settled = settled;
            double hold = Now + 2;
            bool maintained = settled;
            while (Now < hold && maintained)
            {
                bool received = demo.client.TryGetLatestFrame(out BrainFrame frame, out double age);
                var motor = demo.controller.CurrentMotor;
                maintained = Healthy(stop) && received && age <= .75 && frame != null
                    && MatchesApplied(frame, stop.appliedSequence, stop.requestId, stop.brainSessionId, stop.brainInstanceId, "STOP")
                    && frame.requestedAction == "STOP" && frame.motor != null
                    && Mathf.Abs(frame.motor.forward) < .01f && Mathf.Abs(frame.motor.turn) < .01f
                    && Mathf.Abs(motor.forward) < .03f && Mathf.Abs(motor.turn) < .03f
                    && Vector3.ProjectOnPlane(demo.body.LinearVelocity, Vector3.up).magnitude < .05f
                    && demo.body.GroundContactCount > 0;
                yield return null;
            }
            report.scriptStopMaintained = maintained;
            report.overlapVerified = report.scriptOverlapAtFirstChunk;
            if (!report.scriptOverlapAtFirstChunk) Fail(stop, "script_not_playing_at_first_fixture_chunk");
            if (!settled || !maintained) Fail(stop, "script_interrupt_stop_not_maintained");
            if (report.scriptDiscardReceivedAt < stop.firstAudioAt) Fail(stop, "script_discard_not_observed_after_input");
            EndCase(stop, stop.applied && settled && maintained && report.scriptOverlapAtFirstChunk);
            if (stop.status != "pass") SetRunError(stop);
        }

        IEnumerator RunSmoke()
        {
            Case forward = Begin("forward8");
            if (forward == null) yield break;
            yield return AwaitApplied(forward, 25);
            if (!forward.applied) { SetRunError(forward); yield break; }
            double startDeadline = Math.Min(deadline, Now + 8);
            while (Now < startDeadline && !forward.bodyStarted && Healthy(forward)) yield return null;
            if (!forward.bodyStarted) { Fail(forward, "body_not_started_before_stop"); SetRunError(forward); yield break; }
            EndCase(forward, true);
            Case stop = Begin("stop");
            if (stop == null) yield break;
            yield return AwaitApplied(stop, 20);
            bool stopSettled = false;
            if (stop.applied) yield return WaitStopped(20, value => stopSettled = value, stop.appliedSequence, stop.requestId);
            stop.settled = stopSettled;
            stop.voiceStopBeforeExpiry = stop.applied && NoSafetyStopBetween(forward.appliedAt, stop.appliedAt);
            if (!stop.voiceStopBeforeExpiry) Fail(stop, "voice_stop_causality_not_confirmed");
            if (!stop.settled) Fail(stop, "voice_stop_not_settled");
            if (stop.settled) stop.fixtureToSettledMs = (Now - stop.firstAudioAt) * 1000;
            EndCase(stop, stop.settled && stop.voiceStopBeforeExpiry);
            if (stop.status != "pass") { SetRunError(stop); yield break; }

            yield return RunExpiryCase("right8", true);
            string[] repeats = { "ambiguous_forward", "ambiguous_right", "forward8" };
            foreach (string id in repeats)
            {
                if (!string.IsNullOrEmpty(report.error)) yield break;
                int epoch = controller.ControlEpoch, generation = controller.ConversationGeneration;
                string session = controller.BrainSessionId;
                yield return RunExpiryCase(id, false);
                if (string.IsNullOrEmpty(report.error) && current != null && current.applied
                    && epoch == controller.ControlEpoch && generation == controller.ConversationGeneration && session == controller.BrainSessionId)
                    report.ttlReacceptChecks++;
                Save();
            }
        }

        // English demo is intentionally a short functional sequence, not a transcript or microphone test.
        // Each step still uses the same fixture-to-control, real Brain-frame, movement, and STOP gates as smoke.
        IEnumerator RunEnglishDemo()
        {
            Case continueCase = Begin("02_continue");
            if (continueCase == null) yield break;
            yield return AwaitApplied(continueCase, 20);
            if (!continueCase.applied) { SetRunError(continueCase); yield break; }
            double startedDeadline = Math.Min(deadline, Now + 8);
            while (Now < startedDeadline && !continueCase.bodyStarted && Healthy(continueCase)) yield return null;
            if (!continueCase.bodyStarted) { Fail(continueCase, "body_not_started_before_stop"); SetRunError(continueCase); yield break; }
            EndCase(continueCase, true);
            if (recordingStartedAt >= 0)
            {
                double holdUntil = Math.Min(deadline, Now + 15);
                while (Now < holdUntil && Healthy(continueCase)) yield return null;
                if (Now < holdUntil) { Fail(continueCase, "recording_forward_hold_unhealthy"); SetRunError(continueCase); yield break; }
            }

            Case firstStop = Begin("07_stop");
            if (firstStop == null) yield break;
            yield return AwaitApplied(firstStop, 20);
            bool firstStopSettled = false;
            if (firstStop.applied) yield return WaitStopped(20, value => firstStopSettled = value, firstStop.appliedSequence, firstStop.requestId);
            firstStop.settled = firstStopSettled;
            firstStop.voiceStopBeforeExpiry = firstStop.applied && NoSafetyStopBetween(continueCase.appliedAt, firstStop.appliedAt);
            if (!firstStop.voiceStopBeforeExpiry) Fail(firstStop, "voice_stop_causality_not_confirmed");
            if (!firstStop.settled) Fail(firstStop, "voice_stop_not_settled");
            EndCase(firstStop, firstStop.settled && firstStop.voiceStopBeforeExpiry);
            if (firstStop.status != "pass") { SetRunError(firstStop); yield break; }

            Case resume = Begin("05_resume");
            if (resume == null) yield break;
            yield return AwaitApplied(resume, 20);
            if (!resume.applied) { SetRunError(resume); yield break; }
            double resumeDeadline = Math.Min(deadline, Now + 8);
            while (Now < resumeDeadline && !resume.bodyStarted && Healthy(resume)) yield return null;
            if (!resume.bodyStarted) { Fail(resume, "body_not_started_before_stop"); SetRunError(resume); yield break; }
            EndCase(resume, true);

            Case finalStop = Begin("07_stop");
            if (finalStop == null) yield break;
            yield return AwaitApplied(finalStop, 20);
            bool finalStopSettled = false;
            if (finalStop.applied) yield return WaitStopped(20, value => finalStopSettled = value, finalStop.appliedSequence, finalStop.requestId);
            finalStop.settled = finalStopSettled;
            finalStop.voiceStopBeforeExpiry = finalStop.applied && NoSafetyStopBetween(resume.appliedAt, finalStop.appliedAt);
            if (!finalStop.voiceStopBeforeExpiry) Fail(finalStop, "voice_stop_causality_not_confirmed");
            if (!finalStop.settled) Fail(finalStop, "voice_stop_not_settled");
            EndCase(finalStop, finalStop.settled && finalStop.voiceStopBeforeExpiry);
            if (finalStop.status != "pass") SetRunError(finalStop);
        }

        IEnumerator RunEnglishChatDemo()
        {
            Case forward = Begin("02_continue");
            if (forward == null) yield break;
            yield return AwaitApplied(forward, 20);
            if (!forward.applied) { SetRunError(forward); yield break; }
            double forwardDeadline = Math.Min(deadline, Now + 8);
            while (Now < forwardDeadline && !forward.bodyStarted && Healthy(forward)) yield return null;
            if (!forward.bodyStarted) { Fail(forward, "body_not_started_before_question"); SetRunError(forward); yield break; }
            EndCase(forward, true);

            yield return RunEnglishQuestion("10_mood");
            if (!CanContinueChatAfterQuestion()) yield break;
            yield return RunEnglishQuestion("11_hungry");
            if (!CanContinueChatAfterQuestion()) yield break;

            Case stop = Begin("07_stop");
            if (stop == null) yield break;
            yield return AwaitApplied(stop, 20);
            bool stopped = false;
            if (stop.applied) yield return WaitStopped(20, value => stopped = value, stop.appliedSequence, stop.requestId);
            stop.settled = stopped;
            stop.voiceStopBeforeExpiry = stop.applied && NoSafetyStopBetween(forward.appliedAt, stop.appliedAt);
            if (!stop.voiceStopBeforeExpiry) Fail(stop, "voice_stop_causality_not_confirmed");
            if (!stop.settled) Fail(stop, "voice_stop_not_settled");
            EndCase(stop, stop.settled && stop.voiceStopBeforeExpiry);
            if (stop.status != "pass")
            {
                SetRunError(stop);
                if (!stop.applied || !stop.settled || stop.error != "voice_stop_causality_not_confirmed") yield break;
            }

            yield return RunEnglishQuestion("12_fly_life");
            if (!CanContinueChatAfterQuestion()) yield break;

            Case resume = Begin("05_resume");
            if (resume == null) yield break;
            yield return AwaitApplied(resume, 20);
            if (!resume.applied) { SetRunError(resume); yield break; }
            double resumeDeadline = Math.Min(deadline, Now + 8);
            while (Now < resumeDeadline && !resume.bodyStarted && Healthy(resume)) yield return null;
            if (!resume.bodyStarted) { Fail(resume, "body_not_started_before_stop"); SetRunError(resume); yield break; }
            EndCase(resume, true);

            Case finalStop = Begin("07_stop");
            if (finalStop == null) yield break;
            yield return AwaitApplied(finalStop, 20);
            bool finalStopped = false;
            if (finalStop.applied) yield return WaitStopped(20, value => finalStopped = value, finalStop.appliedSequence, finalStop.requestId);
            finalStop.settled = finalStopped;
            finalStop.voiceStopBeforeExpiry = finalStop.applied && NoSafetyStopBetween(resume.appliedAt, finalStop.appliedAt);
            if (!finalStop.voiceStopBeforeExpiry) Fail(finalStop, "voice_stop_causality_not_confirmed");
            if (!finalStop.settled) Fail(finalStop, "voice_stop_not_settled");
            EndCase(finalStop, finalStop.settled && finalStop.voiceStopBeforeExpiry);
            if (finalStop.status != "pass") SetRunError(finalStop);
        }

        IEnumerator RunEnglishQuestion(string id)
        {
            double quietDeadline = Math.Min(deadline, Now + 12);
            while (controller.ReplyPlaying && Now < quietDeadline && CanObserve()) yield return null;
            if (controller.ReplyPlaying) { report.error = "question_prior_reply_not_quiet"; yield break; }
            Case item = Begin(id);
            if (item == null) yield break;
            double classificationDeadline = -1;
            double replyDeadline = -1;
            double quietSince = -1;
            while (Now < deadline && Healthy(item))
            {
                if (playing == null && classificationDeadline < 0)
                {
                    // A long PCM fixture must not consume the response allowance. Both
                    // limits begin only after its final chunk has been sent.
                    classificationDeadline = Math.Min(deadline, Now + 12);
                    replyDeadline = Math.Min(deadline, Now + 18);
                }
                if (!string.IsNullOrEmpty(item.actualKind) && item.actualKind != "question" && item.actualKind != "clarify")
                { Fail(item, "question_classified_as_actionable_intent"); break; }
                if (UnexpectedQuestionAction(item)) { Fail(item, "question_submitted_action"); break; }
                if ((item.actualKind == "question" || item.actualKind == "clarify") && item.correlation == "fixture_audio_overlap")
                {
                    if (!item.replyStarted && controller.ReplyPlaying && controller.PlayedNonzeroSamples > item.replySamplesAtStart)
                        item.replyStarted = true;
                    if (item.replyStarted && !controller.ReplyPlaying && playing == null)
                    {
                        if (quietSince < 0) quietSince = Now;
                        else if (Now - quietSince >= .3) { item.replyCompleted = true; break; }
                    }
                    else quietSince = -1;
                }
                if (classificationDeadline >= 0 && string.IsNullOrEmpty(item.actualKind) && Now >= classificationDeadline)
                { Fail(item, "question_classification_not_observed"); break; }
                if (replyDeadline >= 0 && Now >= replyDeadline) break;
                yield return null;
            }
            if (!item.replyStarted && string.IsNullOrEmpty(item.error)) Fail(item, "question_reply_not_started");
            if (item.replyStarted && !item.replyCompleted && string.IsNullOrEmpty(item.error)) Fail(item, "question_reply_not_completed");
            if (UnexpectedQuestionAction(item)) Fail(item, "question_submitted_action");
            EndCase(item, (item.actualKind == "question" || item.actualKind == "clarify") && item.correlation == "fixture_audio_overlap"
                && item.replyStarted && item.replyCompleted && string.IsNullOrEmpty(item.error));
            if (item.status != "pass") SetRunError(item);
        }

        bool UnexpectedQuestionAction(Case item) => controls.Exists(control => control.localTime >= item.startedAt
            && control.@event == "command_submitted" && control.source != "safety" && !string.IsNullOrEmpty(control.action));

        bool CanContinueChatAfterQuestion() => current != null && (current.status == "pass"
            || current.error == "question_reply_not_completed");

        IEnumerator RunExpiryCase(string id, bool overlap)
        {
            if (overlap)
            {
                long played = controller.PlayedNonzeroSamples;
                double until = Math.Min(deadline, Now + 12);
                while (Now < until && CanObserve() && !(controller.ReplyPlaying && controller.PlayedNonzeroSamples > played)) yield return null;
            }
            Case item = Begin(id);
            if (item == null) yield break;
            item.replyOverlapRequested = overlap;
            yield return AwaitApplied(item, 25);
            if (!item.applied) { SetRunError(item); yield break; }
            double untilExpiry = Math.Min(deadline, Now + 15);
            Control expired = null, appliedStop = null;
            while (Now < untilExpiry && Healthy(item))
            {
                expired = Find("command_expired", item.appliedAt);
                if (expired != null)
                {
                    Control submitted = FindSafetyStop(expired.localTime);
                    if (submitted != null) appliedStop = FindCommand("command_applied", submitted.commandId);
                    if (appliedStop != null) break;
                }
                yield return null;
            }
            item.expired = expired != null && appliedStop != null;
            item.continuedListening = expired != null && expired.continuedListening;
            if (report.suite == "duration")
            {
                Control submission = FindCommand("command_submitted", item.commandId);
                Control classification = FindCommand("intent_classified", item.commandId);
                if (submission == null || classification == null || expired == null)
                    Fail(item, "execution_duration_evidence_missing");
                else
                {
                    item.acceptedExecutionDurationMs = submission.executionDurationMs;
                    item.submittedToExpiryMs = expired.monotonicMs - submission.monotonicMs;
                    if (submission.executionDurationMs <= 0 || submission.executionDurationMs != classification.proposalValidForMs
                        || item.submittedToExpiryMs < submission.executionDurationMs - 50
                        || item.submittedToExpiryMs > submission.executionDurationMs + 750)
                        Fail(item, "execution_duration_not_preserved");
                }
            }
            bool settled = false;
            if (item.expired) yield return WaitStopped(20, value => settled = value, appliedStop.sequence, appliedStop.requestId);
            item.settled = settled;
            if (overlap) report.overlapVerified = item.replyOverlap;
            if (!item.expired || !item.continuedListening) Fail(item, "ttl_stop_not_confirmed");
            if (!settled) Fail(item, "ttl_stop_not_settled");
            if (!MovementPassed(item)) Fail(item, "body_motion_not_confirmed");
            if (controls.Exists(x => x.@event == "command_submitted" && x.localTime > item.appliedAt
                && x.action != "STOP" && x.commandId != item.commandId)) Fail(item, "unexpected_movement_submission");
            EndCase(item, item.expired && item.continuedListening && settled && MovementPassed(item));
            if (item.status != "pass") SetRunError(item);
        }

        IEnumerator RunDuration()
        {
            string[] ids = { "forward_default", "right_default", "left_default" };
            foreach (string id in ids)
            {
                if (!string.IsNullOrEmpty(report.error)) yield break;
                yield return RunExpiryCase(id, false);
            }
        }

        IEnumerator RunFull()
        {
            string[] ids = { "stop", "forward8", "right8", "left8", "forward_right8", "forward_left8" };
            for (int repeat = 0; repeat < 3 && string.IsNullOrEmpty(report.error); repeat++)
                foreach (string id in ids)
                {
                    if (!CanObserve() || Now >= deadline) { report.error = "full_boundary_unavailable"; yield break; }
                    RestoreBaseline();
                    bool settled = false;
                    yield return WaitStopped(15, value => settled = value);
                    if (!settled) { report.error = "full_physics_settle_timeout"; yield break; }
                    if (id == "stop")
                    {
                        Case item = Begin(id);
                        if (item == null) yield break;
                        yield return AwaitApplied(item, 25);
                        bool stopped = false;
                        if (item.applied) yield return WaitStopped(15, value => stopped = value, item.appliedSequence, item.requestId);
                        item.settled = stopped;
                        EndCase(item, item.applied && stopped);
                        if (item.status != "pass") { SetRunError(item); yield break; }
                    }
                    else yield return RunExpiryCase(id, false);
                    if (!string.IsNullOrEmpty(report.error)) yield break;
                }
        }

        IEnumerator RunPersistent(double holdSeconds = 60)
        {
            // A simple persistent Action is the first acceptance gate. Hazard-monitored
            // plans can legitimately stop at a stage edge and are covered separately.
            Case held = Begin("persistent_forward");
            if (held == null) yield break;
            yield return AwaitApplied(held, 25);
            if (!held.applied || held.correlation != "fixture_audio_overlap") { SetRunError(held); yield break; }
            yield return ObservePersistent(held, holdSeconds);
            if (!report.persistentHeld) { SetRunError(held); yield break; }
            string executionId = held.executionId;
            int executionRequest = held.requestId;

            Case continued = Begin("persistent_continue");
            if (continued == null) yield break;
            yield return AwaitExecutionUpdate(continued, executionId, executionRequest, "until_next_command", false);
            report.persistentContinued = continued.status == "pass";
            // Preserve this failure, but still verify that the player can stop
            // the running operation. Every subsequent case has its own health gate.
            if (!report.persistentContinued) SetRunError(continued);

            Case stop = Begin("stop");
            if (stop == null) yield break;
            yield return AwaitApplied(stop, 20);
            bool stopped = false;
            if (stop.applied) yield return WaitStopped(20, value => stopped = value, stop.appliedSequence, stop.requestId);
            stop.settled = stopped;
            stop.voiceStopBeforeExpiry = stop.applied && NoSafetyStopBetween(continued.startedAt, stop.appliedAt);
            EndCase(stop, stopped && stop.voiceStopBeforeExpiry);
            report.persistentStopped = stop.status == "pass";
            if (!report.persistentStopped) { SetRunError(stop); yield break; }

            // The finite command must replace a newly accepted persistent execution,
            // rather than merely follow the STOP that cleared the first one.
            Case replacement = Begin("persistent_forward");
            if (replacement == null) yield break;
            yield return AwaitApplied(replacement, 25);
            if (!replacement.applied || replacement.correlation != "fixture_audio_overlap") { SetRunError(replacement); yield break; }
            yield return AwaitPersistentReady(replacement);
            if (replacement.status != "pass") { SetRunError(replacement); yield break; }

            Case finite = Begin("forward8");
            if (finite == null) yield break;
            yield return AwaitApplied(finite, 25);
            if (!finite.applied || finite.correlation != "fixture_audio_overlap") { SetRunError(finite); yield break; }
            string finiteExecutionId = activeExecution == null ? null : activeExecution.executionId;
            if (string.IsNullOrEmpty(finiteExecutionId) || finiteExecutionId == replacement.executionId)
            { Fail(finite, "finite_command_did_not_replace_persistent_execution"); SetRunError(finite); yield break; }
            double remainingBeforeConditions = activeExecution == null ? 0 : activeExecution.remainingMs;
            Case conditions = Begin("persistent_conditions");
            if (conditions == null) yield break;
            yield return AwaitExecutionUpdate(conditions, finiteExecutionId, finite.requestId, "timed", true);
            if (!conditions.executionUpdated || activeExecution == null || activeExecution.remainingMs <= 0
                || activeExecution.remainingMs > remainingBeforeConditions)
            { Fail(conditions, "condition_update_deadline_not_preserved"); SetRunError(conditions); }
            yield return AwaitFiniteExpiry(finite);
            report.persistentFiniteExpired = finite.status == "pass" && finite.expired && finite.settled;
            if (!report.persistentFiniteExpired) yield break;
            yield return ConfirmNoPersistentRevival(replacement.executionId, finite);
            if (!report.persistentNoRevival && finite != null) SetRunError(finite);
        }

        IEnumerator ObservePersistent(Case item, double seconds)
        {
            double started = Now, windowStarted = Now;
            Vector3 windowStart = demo.body.Position;
            while (Now - started < seconds && Healthy(item))
            {
                if (Now >= deadline) { Fail(item, "persistent_run_deadline_reached"); break; }
                if (activeExecution == null || activeExecution.action != "FORWARD"
                    || activeExecution.executionMode != "until_next_command" || string.IsNullOrEmpty(activeExecution.executionId))
                {
                    Fail(item, "persistent_execution_changed_or_missing"); break;
                }
                if (string.IsNullOrEmpty(item.executionId)) { item.executionId = activeExecution.executionId; item.executionMode = activeExecution.executionMode; }
                else if (item.executionId != activeExecution.executionId || item.executionMode != activeExecution.executionMode)
                { Fail(item, "persistent_execution_changed_or_missing"); break; }
                if (Now - windowStarted >= 10)
                {
                    if (Vector3.ProjectOnPlane(demo.body.Position - windowStart, Vector3.up).magnitude <= .001f)
                    { Fail(item, "persistent_motion_window_stalled"); break; }
                    windowStart = demo.body.Position; windowStarted = Now;
                }
                yield return null;
            }
            if (string.IsNullOrEmpty(item.error) && Now - started >= seconds
                && Vector3.ProjectOnPlane(demo.body.Position - windowStart, Vector3.up).magnitude <= .001f)
                Fail(item, "persistent_motion_window_stalled");
            report.persistentObservationSeconds = Math.Max(0, Now - started);
            report.persistentHeld = Now - started >= seconds && string.IsNullOrEmpty(item.error) && item.executionMode == "until_next_command"
                && !string.IsNullOrEmpty(item.executionId) && item.freshFrameAdvances >= 10 && MovementPassed(item);
            if (!report.persistentHeld) Fail(item, "persistent_execution_not_held");
            EndCase(item, report.persistentHeld);
        }

        IEnumerator AwaitExecutionUpdate(Case item, string expectedExecutionId, int expectedRequestId,
            string expectedMode, bool requireMonitoring)
        {
            double until = Math.Min(deadline, Now + 25);
            while (Now < until && Healthy(item))
            {
                Control update = Find("execution_updated", item.startedAt);
                bool same = activeExecution != null && activeExecution.executionId == expectedExecutionId
                    && activeExecution.action == "FORWARD" && activeExecution.executionMode == expectedMode
                    && activeExecution.monitorHazards == requireMonitoring;
                bool correlated = !string.IsNullOrEmpty(item.commandId) && item.correlation == "fixture_audio_overlap"
                    && update != null && update.commandId == item.commandId;
                if (correlated && same)
                {
                    item.executionId = expectedExecutionId; item.executionMode = activeExecution.executionMode;
                    item.executionUpdated = true;
                    if (item.actualKind != item.expectedKind || item.actualAction != item.expectedAction)
                    { Fail(item, "unexpected_execution_update"); break; }
                    bool resent = controls.Exists(x => x.@event == "command_submitted" && x.localTime >= item.startedAt
                        && x.action == "FORWARD" && x.requestId != expectedRequestId);
                    if (!resent) { EndCase(item, true); yield break; }
                    Fail(item, "persistent_continue_resent_brain_action");
                    break;
                }
                yield return null;
            }
            if (!item.executionUpdated) Fail(item, "execution_update_not_confirmed");
            EndCase(item, false);
        }

        IEnumerator AwaitPersistentReady(Case item)
        {
            double until = Math.Min(deadline, Now + 8);
            while (Now < until && Healthy(item))
            {
                if (activeExecution != null && activeExecution.action == "FORWARD"
                    && activeExecution.executionMode == "until_next_command" && !string.IsNullOrEmpty(activeExecution.executionId))
                {
                    item.executionId = activeExecution.executionId; item.executionMode = activeExecution.executionMode;
                    EndCase(item, true); yield break;
                }
                yield return null;
            }
            Fail(item, "persistent_replacement_execution_unavailable"); EndCase(item, false);
        }

        IEnumerator AwaitFiniteExpiry(Case item)
        {
            double until = Math.Min(deadline, Now + 20);
            Control expired = null, appliedStop = null;
            while (Now < until && Healthy(item))
            {
                expired = Find("command_expired", item.appliedAt);
                Control submittedStop = FindSafetyStop(item.appliedAt);
                appliedStop = submittedStop == null ? null : FindCommand("command_applied", submittedStop.commandId);
                if (expired != null && appliedStop != null) break;
                yield return null;
            }
            item.expired = expired != null && appliedStop != null;
            bool settled = false;
            if (item.expired) yield return WaitStopped(15, value => settled = value, appliedStop.sequence, appliedStop.requestId);
            item.settled = settled;
            item.continuedListening = expired != null && expired.continuedListening;
            if (!item.expired) Fail(item, "timed_replacement_expiry_not_confirmed");
            if (!settled) Fail(item, "timed_replacement_stop_not_settled");
            EndCase(item, item.expired && settled && item.continuedListening);
        }

        IEnumerator ConfirmNoPersistentRevival(string oldExecutionId, Case item)
        {
            double until = Now + 3;
            while (Now < until && Now < deadline && Healthy(item))
            {
                if (activeExecution != null && activeExecution.executionId == oldExecutionId)
                { Fail(item, "old_persistent_execution_revived"); yield break; }
                yield return null;
            }
            if (Now < until) Fail(item, "persistent_revival_observation_incomplete");
            report.persistentNoRevival = string.IsNullOrEmpty(item.error);
        }

        IEnumerator RunPlans()
        {
            foreach (Fixture fixture in fixtures.Values)
            {
                if (fixture.expectedKind != "plan") continue;
                Case item = Begin(fixture.id);
                if (item == null) yield break;
                yield return AwaitApplied(item, 25);
                // Future real-sensor plan execution still needs its own multi-step physical acceptance gate.
                if (item.actualKind == "plan" && item.actualPlan == item.expectedPlan && item.correlation == "fixture_audio_overlap")
                {
                    if (item.error == "local_observation_unavailable" || item.error == "local_observation_unknown") item.status = "blocked";
                    else
                    {
                        item.status = "incomplete";
                        if (string.IsNullOrEmpty(item.error)) item.error = "plan_body_acceptance_not_implemented";
                    }
                }
                else
                {
                    item.status = "incomplete";
                    item.error = item.correlation != "fixture_audio_overlap" ? "plan_fixture_correlation_missing" : "expected_plan_not_classified";
                }
                item.endedAt = Now; Save();
                if (!CanObserve()) break;
            }
            report.error = report.cases.TrueForAll(x => x.status == "blocked")
                ? "plans_require_real_local_safety_observation" : "plan_acceptance_incomplete";
        }

        Case Begin(string id)
        {
            if (!fixtures.TryGetValue(id, out Fixture fixture)) { report.error = "missing_fixture_" + id; Save(); return null; }
            if (Now >= deadline || !CanObserve() || playing != null) { report.error = "fixture_start_boundary_unavailable"; Save(); return null; }
            current = new Case { id = "case_" + (report.cases.Count + 1).ToString(CultureInfo.InvariantCulture),
                fixtureId = id, fixtureHash = fixture.clip.Sha256, expectedKind = fixture.expectedKind,
                durationSeconds = fixture.clip.DurationSeconds, sourceSampleRate = fixture.clip.SourceSampleRate, sourceChannels = fixture.clip.SourceChannels,
                expectedAction = fixture.expectedAction, expectedPlan = fixture.expectedPlan,
                epoch = controller.ControlEpoch, generation = controller.ConversationGeneration,
                brainSessionId = controller.BrainSessionId, brainInstanceId = controller.BrainInstanceId,
                startedAt = Now, startPosition = demo.body.Position, previousPosition = demo.body.Position,
                previousYaw = Thorax.eulerAngles.y, previousPhase = demo.controller.Phase,
                initialForward = Vector3.ProjectOnPlane(Thorax.forward, Vector3.up).normalized,
                replySamplesAtStart = controller.PlayedNonzeroSamples };
            report.cases.Add(current);
            playing = fixture; chunkIndex = 0;
            audioEpoch = current.epoch; audioGeneration = current.generation;
            Log("fixture_queued", id);
            Save();
            return current;
        }

        IEnumerator AwaitApplied(Case item, double seconds)
        {
            double until = Math.Min(deadline, Now + seconds);
            while (Now < until && Healthy(item))
            {
                if (!string.IsNullOrEmpty(item.actualKind) && item.actualKind != "action")
                {
                    while (playing != null && Now < until && CanObserve()) yield return null;
                    if (item.actualKind == "plan")
                    {
                        double planUntil = Math.Min(until, Now + 3);
                        while (Now < planUntil && string.IsNullOrEmpty(item.error)) yield return null;
                        Correlate(item);
                        if (item.correlation != "fixture_audio_overlap") { item.status = "incomplete"; item.error = "plan_fixture_correlation_missing"; }
                        else if (item.expectedKind == "plan" && item.actualPlan != item.expectedPlan) { item.status = "incomplete"; item.error = "unexpected_plan"; }
                        else if (item.error == "local_observation_unavailable" || item.error == "local_observation_unknown") item.status = "blocked";
                        else { item.status = "incomplete"; if (string.IsNullOrEmpty(item.error)) item.error = "plan_body_acceptance_not_implemented"; }
                    }
                    else Fail(item, "classified_" + item.actualKind);
                    item.endedAt = Now; Save(); yield break;
                }
                if (item.applied && item.correlation == "fixture_audio_overlap" && playing == null)
                {
                    if (item.actualAction != item.expectedAction) Fail(item, "unexpected_action");
                    yield break;
                }
                if (!string.IsNullOrEmpty(item.error)) yield break;
                yield return null;
            }
            if (string.IsNullOrEmpty(item.error)) Fail(item, item.applied ? "delegation_fixture_correlation_missing" : "voice_apply_timeout");
            item.endedAt = Now; Save();
        }

        IEnumerator WaitStopped(double seconds, Action<bool> done, long expectedSequence = 0, int expectedRequestId = 0)
        {
            double until = Math.Min(deadline, Now + seconds), stable = -1;
            while (Now < until && CanObserve())
            {
                bool received = demo.client.TryGetLatestFrame(out BrainFrame frame, out double age);
                var motor = demo.controller.CurrentMotor;
                bool matched = expectedSequence == 0 || MatchesApplied(frame, expectedSequence, expectedRequestId,
                    controller.BrainSessionId, controller.BrainInstanceId, "STOP");
                bool quiet = received && matched && age <= .75 && frame != null && frame.requestedAction == "STOP" && frame.motor != null
                    && Mathf.Abs(frame.motor.forward) < .01f && Mathf.Abs(frame.motor.turn) < .01f
                    && Mathf.Abs(motor.forward) < .03f && Mathf.Abs(motor.turn) < .03f
                    && Vector3.ProjectOnPlane(demo.body.LinearVelocity, Vector3.up).magnitude < .05f
                    && demo.body.GroundContactCount > 0;
                if (quiet) { if (stable < 0) stable = Now; if (Now - stable >= .5) { done(true); yield break; } }
                else stable = -1;
                yield return null;
            }
            done(false);
        }

        void Update()
        {
            SilenceScriptProducer();
            if (!running || controller == null) return;
            if (current != null && current.status == "pending") ObserveCase(current);
            if (Now >= nextObservationAt) { WriteObservation(); nextObservationAt = Now + .2; }
            if (playing != null && (controller.ControlEpoch != audioEpoch || controller.ConversationGeneration != audioGeneration
                || controller.MicrophoneMuted || !controller.FixtureInputTransmitting))
            {
                Log("fixture_remainder_discarded", playing.id);
                if (current != null) Fail(current, "fixture_input_boundary_changed");
                playing = null;
            }
            if (!controller.FixtureInputTransmitting) { nextAudioAt = audioNotBefore = Now; return; }
            if (Now < Math.Max(nextAudioAt, audioNotBefore)) return;
            // Preserve the ideal PCM clock through frame jitter. One chunk per Update,
            // with a 90 ms minimum spacing, bounds recovery after a delayed frame.
            double sendStarted = Now;
            byte[] pcm = playing == null ? silence : playing.clip.Chunks[chunkIndex];
            string id = playing == null ? null : current.id;
            int index = playing == null ? -1 : chunkIndex;
            int epoch = playing == null ? controller.ControlEpoch : audioEpoch;
            int generation = playing == null ? controller.ConversationGeneration : audioGeneration;
            if (!controller.TrySendFixturePcm(pcm, epoch, generation, id, index))
            {
                if (playing != null && current != null) Fail(current, "fixture_chunk_not_sent");
                playing = null; nextAudioAt = Now + .1; audioNotBefore = Now + .09; return;
            }
            // This opt-in local speaker monitor uses the exact converted PCM sent above.
            // It remains separate from fixture input, so the microphone stays disabled.
            if (monitorFixtures && playing != null && chunkIndex == 0) PlayFixtureMonitor(playing);
            if (previousAudioAt >= 0)
            {
                double intervalMs = (sendStarted - previousAudioAt) * 1000;
                report.maxSendIntervalMs = Math.Max(report.maxSendIntervalMs, intervalMs);
                report.minSendIntervalMs = report.minSendIntervalMs <= 0 ? intervalMs : Math.Min(report.minSendIntervalMs, intervalMs);
            }
            previousAudioAt = sendStarted; nextAudioAt += .1; audioNotBefore = sendStarted + .09;
            if (playing != null)
            {
                if (chunkIndex == 0) { if (report.suite == "script_interrupt")
                    report.scriptOverlapAtFirstChunk = controller.ReplyPlaying && controller.PlayedNonzeroSamples > report.scriptSamplesBefore;
                    current.firstAudioAt = Now; current.sourceSampleStart = sampleCursor; Log("fixture_audio_started", id); }
                current.sentChunks++; current.lastAudioAt = Now;
                current.replyOverlap |= controller.ReplyPlaying && controller.PlayedNonzeroSamples > current.replySamplesAtStart;
                chunkIndex++;
                if (chunkIndex >= playing.clip.Chunks.Length)
                {
                    current.sourceSampleEnd = sampleCursor + pcm.Length / 2;
                    Log("fixture_audio_finished", id); playing = null;
                }
            }
            sampleCursor += pcm.Length / 2;
        }

        void PlayFixtureMonitor(Fixture fixture)
        {
            if (fixture == null || fixture.clip == null) return;
            if (monitorSource == null)
            {
                monitorObject = new GameObject("Native fixture audio monitor");
                monitorObject.transform.SetParent(transform, false);
                monitorSource = monitorObject.AddComponent<AudioSource>();
                monitorSource.playOnAwake = false;
                monitorSource.loop = false;
                monitorSource.spatialBlend = 0f;
            }
            if (fixture.monitorClip == null) fixture.monitorClip = CreateMonitorClip(fixture);
            if (fixture.monitorClip == null) return;
            monitorSource.Stop();
            monitorSource.clip = fixture.monitorClip;
            monitorSource.time = 0f;
            monitorSource.Play();
        }

        static AudioClip CreateMonitorClip(Fixture fixture)
        {
            const int sampleRate = PcmStreamConverter.TargetSampleRate;
            int samples = 0;
            for (int i = 0; i < fixture.clip.Chunks.Length; i++)
                samples += fixture.clip.Chunks[i] == null ? 0 : fixture.clip.Chunks[i].Length / sizeof(short);
            if (samples <= 0) return null;
            var data = new float[samples];
            int sample = 0;
            for (int i = 0; i < fixture.clip.Chunks.Length; i++)
            {
                byte[] chunk = fixture.clip.Chunks[i];
                if (chunk == null) continue;
                for (int offset = 0; offset + 1 < chunk.Length; offset += sizeof(short))
                    data[sample++] = (short)(chunk[offset] | (chunk[offset + 1] << 8)) / 32768f;
            }
            AudioClip result = AudioClip.Create("Fixture monitor " + fixture.id, samples, 1, sampleRate, false);
            result.SetData(data, 0);
            return result;
        }

        void OnControl(string json)
        {
            Control item;
            try { item = JsonUtility.FromJson<Control>(json); }
            catch (ArgumentException) { return; }
            if (item == null) return;
            if (report != null && report.suite == "script_interrupt")
            {
                if (item.type == "blind_run_cue_result" && item.sequence == 1 && item.stage == "queued" && report.scriptCueSentAt >= 0)
                { report.scriptCueAccepted = true; report.scriptCueAcceptedAt = Now; Log("script_intro_accepted", null); }
                if (item.type == "discard_audio" && current != null && current.firstAudioAt >= 0 && report.scriptDiscardReceivedAt < 0)
                { report.scriptDiscardReceivedAt = Now; Log("script_discard_received", null); }
                if (item.type == "voice_test_diagnostic" && item.@event == "player_speech_interrupt" && report.scriptInterruptDiagnosticAt < 0)
                    report.scriptInterruptDiagnosticAt = Now;
            }
            if (item.type == "conversation_text")
            {
                ObserveInputTranscript(json);
                return; // Caption text never enters Control, lifecycle or event logs.
            }
            if (item.type == "brain_frame")
            {
                // This socket retains the original request ID. The motor TCP deliberately maps GPT IDs to zero.
                UpstreamFrame frame = JsonUtility.FromJson<UpstreamFrame>(json);
                if (frame != null && frame.appliedRequestId > 0 && frame.metadata != null)
                {
                    appliedFrames[frame.appliedRequestId] = frame;
                    if (appliedFrames.Count > 256)
                    {
                        int oldest = int.MaxValue; foreach (int id in appliedFrames.Keys) oldest = Math.Min(oldest, id);
                        appliedFrames.Remove(oldest);
                    }
                    events?.WriteLine(JsonUtility.ToJson(new Entry { @event = "upstream_applied_frame", realtimeSeconds = Now,
                        control = new Control { requestId = frame.appliedRequestId, sequence = frame.sequence,
                            sessionId = frame.metadata.sessionId, instanceId = frame.metadata.instanceId } }));
                }
                return;
            }
            // Never persist raw audio, captions, service replies, or arbitrary JSON fields.
            if (item.type != "voice_test_diagnostic" && item.type != "command_result"
                && item.type != "conversation_state" && item.type != "bridge_state") return;
            item.localTime = Now;
            if (item.type == "bridge_state") activeExecution = item.activeExecution;
            if (item.type == "voice_test_diagnostic")
            {
                item.observedGeneration = controller == null ? -1 : controller.ConversationGeneration;
                item.observedSessionId = controller == null ? null : controller.BrainSessionId;
                item.observedInstanceId = controller == null ? null : controller.BrainInstanceId;
                controls.Add(item);
                if (item.@event == "delegation_observed" && !string.IsNullOrEmpty(item.delegationId)) delegations[item.delegationId] = item;
                if (item.@event == "transcript_candidate_observed" && !string.IsNullOrEmpty(item.inputId)) transcriptCandidates[item.inputId] = item;
                if (item.@event == "controller_released") report.controllerReleasedObserved = true;
                if (item.@event == "bridge_stopped") report.bridgeStoppedObserved = true;
                report.protocolShutdownObserved = report.controllerReleasedObserved && report.bridgeStoppedObserved;
            }
            events?.WriteLine(JsonUtility.ToJson(new Entry { @event = "control", realtimeSeconds = Now, control = item }));
            if (current == null || current.status != "pending" || item.type != "voice_test_diagnostic") return;
            if (item.epoch != current.epoch) return;
            if (item.@event == "audio_fixture_sent" && item.fixtureId == current.id)
            {
                if (current.bridgeAudioStartMs < 0) current.bridgeAudioStartMs = item.audioStartMs;
                current.bridgeAudioEndMs = Math.Max(current.bridgeAudioEndMs, item.audioEndMs);
            }
            if (current.expectedKind == "question" && item.@event == "transcript_candidate_observed"
                && item.utteranceFinalized && !string.IsNullOrEmpty(item.inputId)
                && current.bridgeAudioStartMs >= 0 && current.bridgeAudioEndMs > current.bridgeAudioStartMs
                && item.startMs < current.bridgeAudioEndMs && item.endMs > current.bridgeAudioStartMs)
            {
                if (string.IsNullOrEmpty(current.inputId)) current.inputId = item.inputId;
                else if (current.inputId != item.inputId) Fail(current, "multiple_question_candidates_for_fixture");
            }
            if (current.expectedKind == "question" && item.@event == "transcript_candidate_result"
                && item.inputId == current.inputId)
            { current.actualKind = item.kind; current.actualAction = item.action; current.actualPlan = item.plan; }
            if (item.@event == "voice_intent_dispatch" && item.outcome == "started")
            {
                if (current.firstAudioAt < 0) return;
                if (string.IsNullOrEmpty(item.commandId)) return;
                if (string.IsNullOrEmpty(current.commandId))
                {
                    current.commandId = item.commandId;
                    current.delegationId = item.delegationId;
                    current.inputId = item.inputId;
                    // Semantic candidates cannot claim the case before their committed dispatch.
                }
                else if (current.commandId != item.commandId) Fail(current, "multiple_delegations_for_fixture");
            }
            if (item.commandId == current.commandId && !string.IsNullOrEmpty(current.commandId))
            {
                current.lifecycle.Add(item);
                if (item.@event == "intent_classified") { current.actualKind = item.kind; current.actualAction = item.action; current.actualPlan = item.plan; current.interpretRoute = item.interpretRoute; }
                if (item.@event == "intent_rejected") Fail(current, SafeCode(item.reason));
                if (item.@event == "command_applied")
                {
                    current.applied = true; current.appliedAt = Now;
                    current.requestId = item.requestId; current.appliedSequence = item.sequence;
                    current.fixtureToAppliedMs = (Now - current.firstAudioAt) * 1000;
                    current.audioEndToAppliedMs = current.fixtureToAppliedMs - current.durationSeconds * 1000;
                }
                if (item.@event == "plan_started") current.planId = item.planId;
            }
            if (item.@event == "execution_updated") current.executionUpdated = true;
            if (item.@event == "execution_updated" && item.commandId == current.commandId)
            { current.actualKind = "update"; current.actualAction = item.action; }
            if (!string.IsNullOrEmpty(current.planId) && item.planId == current.planId) current.lifecycle.Add(item);
            Correlate(current);
        }

        void ObserveInputTranscript(string json)
        {
            if (current == null || current.status != "pending" || current.firstAudioAt < 0
                || controller == null || controller.ControlEpoch != current.epoch
                || controller.ConversationGeneration != current.generation
                || !controller.FixtureInputEnabled || controller.MicrophoneCapturing) return;
            InputTranscript transcript;
            try { transcript = JsonUtility.FromJson<InputTranscript>(json); }
            catch (ArgumentException) { return; }
            if (transcript == null || transcript.role != "user" || string.IsNullOrEmpty(transcript.text)
                || transcript.conversationGeneration != current.generation) return;
            if (!transcript.append)
            {
                current.recognizedText.Clear();
                current.recognizedTextOverflow = false;
            }
            int remaining = 2000 - current.recognizedText.Length;
            int count = Math.Min(remaining, transcript.text.Length);
            current.recognizedText.Append(transcript.text, 0, count);
            current.recognizedTextOverflow |= count < transcript.text.Length;
            // Count the bounded received UTF-16 characters, before comparison normalization.
            current.recognizedCharacterCount = current.recognizedText.Length;
            current.recognizedMatchesFixture = false;
            if (current.recognizedTextOverflow || !fixtures.TryGetValue(current.fixtureId, out Fixture manifestFixture)) return;
            try
            {
                string recognized = NormalizeTranscript(current.recognizedText.ToString());
                current.recognizedMatchesFixture = recognized.Length > 0
                    && string.Equals(recognized, NormalizeTranscript(manifestFixture.utterance), StringComparison.Ordinal);
            }
            catch (ArgumentException) { } // Malformed Unicode is a diagnostic mismatch only.
        }

        static string NormalizeTranscript(string value)
        {
            string normalized = (value ?? string.Empty).Normalize(NormalizationForm.FormKC);
            var result = new StringBuilder(normalized.Length);
            foreach (char character in normalized)
                if (!char.IsWhiteSpace(character) && !char.IsPunctuation(character)) result.Append(character);
            return result.ToString();
        }

        void Correlate(Case item)
        {
            if (string.IsNullOrEmpty(item.commandId) && item.expectedKind != "question") return;
            Control evidence;
            string source;
            bool hasDelegation = !string.IsNullOrEmpty(item.delegationId);
            bool hasCandidate = !string.IsNullOrEmpty(item.inputId);
            if (hasDelegation && hasCandidate)
            {
                // Live dispatch may retain a provider delegation ID alongside the finalized
                // transcript input ID. It is one utterance only when the committed command
                // explicitly uses that input ID; never infer this relationship otherwise.
                if (!string.Equals(item.commandId, item.inputId, StringComparison.Ordinal)
                    || !transcriptCandidates.TryGetValue(item.inputId, out evidence)
                    || !evidence.utteranceFinalized) return;
                source = "unified_utterance";
            }
            else if (hasDelegation)
            {
                if (!delegations.TryGetValue(item.delegationId, out evidence)) return;
                source = "client_delegation";
            }
            else if (hasCandidate)
            {
                if (!transcriptCandidates.TryGetValue(item.inputId, out evidence) || !evidence.utteranceFinalized) return;
                source = "transcript_semantic";
            }
            else return;
            if (evidence.epoch != item.epoch || evidence.observedGeneration != item.generation
                || evidence.observedSessionId != item.brainSessionId || evidence.observedInstanceId != item.brainInstanceId
                || evidence.localTime < item.firstAudioAt) return;
            item.intentSource = source;
            item.inputStartMs = evidence.startMs; item.inputEndMs = evidence.endMs; item.inputOffsetMs = evidence.offsetMs;
            if (source == "client_delegation")
            { item.delegationStartMs = evidence.startMs; item.delegationEndMs = evidence.endMs; item.delegationOffsetMs = evidence.offsetMs; }
            if (item.bridgeAudioStartMs >= 0 && item.bridgeAudioEndMs > item.bridgeAudioStartMs
                && evidence.startMs >= 0 && evidence.endMs > evidence.startMs
                && evidence.endMs > item.bridgeAudioStartMs && evidence.startMs < item.bridgeAudioEndMs)
                item.correlation = "fixture_audio_overlap";
        }

        void ObserveCase(Case item)
        {
            if (demo == null || demo.body == null || demo.controller == null) return;
            Vector3 position = demo.body.Position;
            item.endPosition = position;
            item.forwardTravel += Vector3.Dot(Vector3.ProjectOnPlane(position - item.previousPosition, Vector3.up),
                Vector3.ProjectOnPlane(Thorax.forward, Vector3.up).normalized);
            item.yawDegrees += Mathf.DeltaAngle(item.previousYaw, Thorax.eulerAngles.y);
            item.phaseTravel += Mathf.Abs(Mathf.DeltaAngle(item.previousPhase * Mathf.Rad2Deg, demo.controller.Phase * Mathf.Rad2Deg)) * Mathf.Deg2Rad;
            item.previousPosition = position; item.previousYaw = Thorax.eulerAngles.y; item.previousPhase = demo.controller.Phase;
            item.horizontalDisplacement = Vector3.ProjectOnPlane(position - item.startPosition, Vector3.up).magnitude;
            item.forwardDisplacement = Vector3.Dot(position - item.startPosition, item.initialForward);
            var motor = demo.controller.CurrentMotor;
            item.currentForwardPeak = Mathf.Max(item.currentForwardPeak, Mathf.Abs(motor.forward));
            item.currentTurnPeak = Mathf.Max(item.currentTurnPeak, Mathf.Abs(motor.turn));
            item.grounded |= demo.body.GroundContactCount > 0;
            item.sourceMaintained &= demo.controller.MotorSource == demo.live;
            item.sameEpoch &= controller.ControlEpoch == item.epoch && controller.ConversationGeneration == item.generation;
            item.sameSession &= controller.BrainSessionId == item.brainSessionId && controller.BrainInstanceId == item.brainInstanceId;
            if (demo.client.TryGetLatestFrame(out BrainFrame frame, out double age) && frame != null && frame.motor != null)
            {
                item.freshMaintained &= age <= .75;
                item.frameAgeMax = Mathf.Max(item.frameAgeMax, (float)age);
                if (item.applied && age <= .75 && frame.sequence > Math.Max(item.appliedSequence, item.lastFreshSequence))
                { item.freshFrameAdvances++; item.lastFreshSequence = frame.sequence; }
                item.actualForwardPeak = Mathf.Max(item.actualForwardPeak, Mathf.Abs(frame.motor.forward));
                item.actualTurnPeak = Mathf.Max(item.actualTurnPeak, Mathf.Abs(frame.motor.turn));
                if (item.applied && age <= .75 && MatchesApplied(frame, item.appliedSequence, item.requestId,
                    item.brainSessionId, item.brainInstanceId, item.actualAction)) ObservePostApplied(item, frame);
                if (item.applied && frame.sequence >= item.appliedSequence && !item.bodyStarted
                    && MovementPassed(item))
                { item.bodyStarted = true; item.fixtureToBodyStartedMs = (Now - item.firstAudioAt) * 1000;
                    item.audioEndToBodyStartedMs = item.fixtureToBodyStartedMs - item.durationSeconds * 1000;
                    Log("body_started", item.fixtureId); }
            }
            else item.freshMaintained = false;
            item.observedSamples++;
            Correlate(item);
        }

        bool MovementPassed(Case item)
        {
            string action = item.actualAction;
            if (string.IsNullOrEmpty(action) || action == "STOP") return false;
            Motion motion = item.postAppliedMotion;
            if (!motion.matchedAppliedFrame || motion.samples < 2) return false;
            bool forward = !action.StartsWith("FORWARD", StringComparison.Ordinal) || (action == "FORWARD" ? motion.forwardDisplacement > .001f : motion.forwardTravel > .001f);
            bool turn = !action.EndsWith("_R", StringComparison.Ordinal) && !action.EndsWith("_L", StringComparison.Ordinal)
                || (action.EndsWith("_R", StringComparison.Ordinal) ? motion.yawDegrees > .1f : motion.yawDegrees < -.1f);
            bool motor = action.StartsWith("FORWARD", StringComparison.Ordinal)
                ? motion.actualForwardPeak > .03f && motion.currentForwardPeak > .03f
                : motion.actualTurnPeak > .03f && motion.currentTurnPeak > .03f;
            return forward && turn && motor && motion.phaseTravel > .1f && motion.grounded && motion.endPosition.y - motion.startPosition.y >= -.5f;
        }

        bool MatchesApplied(BrainFrame frame, long sequence, int requestId, string session, string instance, string action)
        {
            return sequence > 0 && requestId > 0 && frame != null && frame.metadata != null
                && frame.sequence >= sequence && frame.metadata.sessionId == session && frame.metadata.instanceId == instance
                && frame.requestedAction == action && appliedFrames.TryGetValue(requestId, out UpstreamFrame proof)
                && proof.sequence == sequence && proof.metadata.sessionId == session && proof.metadata.instanceId == instance;
        }

        void ObservePostApplied(Case item, BrainFrame frame)
        {
            Motion motion = item.postAppliedMotion;
            Vector3 position = demo.body.Position;
            if (!motion.matchedAppliedFrame)
            {
                motion.matchedAppliedFrame = true; motion.upstreamRequestId = item.requestId;
                motion.tcpAppliedRequestId = frame.appliedRequestId; motion.firstSequence = frame.sequence; motion.startedAt = Now;
                motion.startPosition = motion.previousPosition = position;
                motion.initialForward = Vector3.ProjectOnPlane(Thorax.forward, Vector3.up).normalized;
                motion.previousYaw = Thorax.eulerAngles.y; motion.previousPhase = demo.controller.Phase;
                Log("post_applied_motion_started", item.fixtureId);
            }
            motion.endPosition = position;
            motion.forwardTravel += Vector3.Dot(Vector3.ProjectOnPlane(position - motion.previousPosition, Vector3.up),
                Vector3.ProjectOnPlane(Thorax.forward, Vector3.up).normalized);
            motion.yawDegrees += Mathf.DeltaAngle(motion.previousYaw, Thorax.eulerAngles.y);
            motion.phaseTravel += Mathf.Abs(Mathf.DeltaAngle(motion.previousPhase * Mathf.Rad2Deg, demo.controller.Phase * Mathf.Rad2Deg)) * Mathf.Deg2Rad;
            motion.horizontalDisplacement = Vector3.ProjectOnPlane(position - motion.startPosition, Vector3.up).magnitude;
            motion.forwardDisplacement = Vector3.Dot(position - motion.startPosition, motion.initialForward);
            motion.previousPosition = position; motion.previousYaw = Thorax.eulerAngles.y; motion.previousPhase = demo.controller.Phase;
            motion.grounded |= demo.body.GroundContactCount > 0;
            motion.actualForwardPeak = Mathf.Max(motion.actualForwardPeak, Mathf.Abs(frame.motor.forward));
            motion.actualTurnPeak = Mathf.Max(motion.actualTurnPeak, Mathf.Abs(frame.motor.turn));
            motion.currentForwardPeak = Mathf.Max(motion.currentForwardPeak, Mathf.Abs(demo.controller.CurrentMotor.forward));
            motion.currentTurnPeak = Mathf.Max(motion.currentTurnPeak, Mathf.Abs(demo.controller.CurrentMotor.turn));
            motion.samples++;
        }

        bool Healthy(Case item)
        {
            if (CanObserve() && controller.ControlEpoch == item.epoch && controller.ConversationGeneration == item.generation
                && controller.BrainSessionId == item.brainSessionId && controller.BrainInstanceId == item.brainInstanceId) return true;
            if (string.IsNullOrEmpty(item.error)) Fail(item, "control_session_or_freshness_changed");
            return false;
        }
        bool CanObserve() => controller != null && controller.BodyControlActive && controller.FixtureInputTransmitting
            && body != null && body.BodyActive && demo != null && demo.client != null && demo.controller != null
            && demo.body != null && demo.body.Thorax != null && demo.controller.MotorSource == demo.live && controller.HasFreshBrain;
        Control Find(string name, double after) => controls.Find(x => x.@event == name && x.localTime >= after);
        Control FindCommand(string name, string id) => controls.Find(x => x.@event == name && x.commandId == id);
        Control FindSafetyStop(double after) => controls.Find(x => x.@event == "command_submitted" && x.localTime >= after
            && x.action == "STOP" && x.source == "safety" && x.commandId != null && x.commandId.StartsWith("expired-stop-", StringComparison.Ordinal));
        bool NoSafetyStopBetween(double from, double to) => !controls.Exists(x => x.localTime >= from && x.localTime <= to
            && (x.@event == "command_expired" || x.@event == "output_inhibited" || (x.@event == "command_submitted" && x.source == "safety" && x.action == "STOP")));

        void EndCase(Case item, bool passed)
        {
            bool accepted = item.expectedKind == "question" ? item.replyStarted && item.replyCompleted : item.applied || item.executionUpdated;
            if (item.status == "pending") item.status = passed && string.IsNullOrEmpty(item.error) && accepted
                && item.correlation == "fixture_audio_overlap" && item.sameEpoch && item.sameSession && item.sourceMaintained && item.freshMaintained ? "pass" : "incomplete";
            item.endedAt = Now; Save();
        }
        void Fail(Case item, string error) { if (string.IsNullOrEmpty(item.error)) item.error = error; }
        void SetRunError(Case item) { report.error = string.IsNullOrEmpty(item.error) ? "case_" + item.status : item.error; EndCase(item, false); }
        void Finish(string error)
        {
            if (playing != null) Log("fixture_remainder_discarded_at_end", playing.id);
            running = false; playing = null;
            report.error = error;
            report.endedAt = Now;
            report.sentFixtureAudioChunks = controller == null ? 0 : controller.SentFixtureAudioChunks;
            report.sentPcmSamples = sampleCursor;
            bool durationPass = report.suite == "duration" && report.cases.Count == 3
                && report.cases.TrueForAll(x => x.status == "pass" && x.expired && x.settled && x.continuedListening);
            bool persistentPass = report.suite == "persistent" && report.persistentObservationSeconds >= 60
                && report.persistentHeld && report.persistentContinued
                && report.persistentStopped && report.persistentFiniteExpired && report.persistentNoRevival;
            bool handoffPass = report.suite == "handoff" && report.persistentObservationSeconds >= 3
                && report.persistentHeld && report.persistentContinued
                && report.persistentStopped && report.persistentFiniteExpired && report.persistentNoRevival;
            bool scriptPass = report.suite == "script_interrupt" && report.scriptCueAccepted
                && report.scriptOverlapAtFirstChunk && report.scriptStopMaintained && report.startupFreshStop
                && report.cases.Count == 1 && report.cases[0].applied && report.cases[0].settled
                && report.scriptDiscardReceivedAt >= report.cases[0].firstAudioAt;
            bool englishDemoPass = report.suite == "english-demo" && report.cases.Count == 4;
            bool englishChatPass = report.suite == "english-chat-demo" && report.cases.Count == 7;
            bool standardPass = report.suite != "duration" && report.suite != "persistent" && report.suite != "handoff" && report.suite != "script_interrupt" && report.suite != "english-demo" && report.suite != "english-chat-demo"
                && report.ttlReacceptChecks >= 3 && report.overlapVerified;
            report.pass = string.IsNullOrEmpty(error) && report.cases.Count > 0 && report.cases.TrueForAll(x => x.status == "pass")
                && (durationPass || persistentPass || handoffPass || scriptPass || englishDemoPass || englishChatPass || standardPass);
            if (report.suite != "duration" && report.suite != "persistent" && report.suite != "handoff" && report.suite != "english-demo" && report.suite != "english-chat-demo" && string.IsNullOrEmpty(report.error) && !report.overlapVerified) report.error = "reply_overlap_not_observed";
            report.status = report.pass ? "pass" : report.cases.Exists(x => x.status == "blocked") ? "blocked" : "incomplete";
            report.result = report.pass ? "native_voice_fixture_pass" : report.status;
            if (monitorSource != null) monitorSource.Stop();
            Save();
        }

        void WriteObservation()
        {
            if (demo == null || demo.body == null || demo.controller == null || demo.client == null) return;
            var sample = new Observation { realtimeSeconds = Now, caseId = current == null ? null : current.id,
                inputSource = controller.InputSource, epoch = controller.ControlEpoch, generation = controller.ConversationGeneration,
                sessionId = controller.BrainSessionId, instanceId = controller.BrainInstanceId, backend = controller.Backend,
                live = controller.ConversationLive, bodyActive = body != null && body.BodyActive,
                sourceEqualsLive = demo.controller.MotorSource == demo.live, fixtureTransmitting = controller.FixtureInputTransmitting,
                microphoneCapturing = controller.MicrophoneCapturing, replyPlaying = controller.ReplyPlaying,
                ready = controller.BrainReady, sentFixtureChunks = controller.SentFixtureAudioChunks,
                playedNonzeroSamples = controller.PlayedNonzeroSamples, position = demo.body.Position,
                velocity = demo.body.LinearVelocity, yawDegrees = Thorax.eulerAngles.y,
                currentForward = demo.controller.CurrentMotor.forward, currentTurn = demo.controller.CurrentMotor.turn,
                error = SafeCode(controller.Error) };
            if (demo.client.TryGetLatestFrame(out BrainFrame frame, out double age) && frame != null && frame.motor != null)
            {
                sample.sequence = frame.sequence; sample.ageSeconds = (float)age;
                sample.actualForward = frame.motor.forward; sample.actualTurn = frame.motor.turn;
                sample.brainStepWallMs = frame.performance == null ? 0 : frame.performance.stepWallTimeMs;
            }
            observations?.WriteLine(JsonUtility.ToJson(sample));
        }

        void CaptureBaseline()
        {
            var root = demo.body.Thorax;
            baseline = new PhysicsBaseline { position = root.transform.position, rotation = root.transform.rotation,
                joints = new List<float>(), phase = demo.controller.Phase };
            root.GetJointPositions(baseline.joints);
        }
        void RestoreBaseline()
        {
            var root = demo.body.Thorax;
            root.TeleportRoot(baseline.position, baseline.rotation); root.SetJointPositions(new List<float>(baseline.joints));
            var zeros = new List<float>(); foreach (float unused in baseline.joints) zeros.Add(0);
            root.SetJointVelocities(zeros); root.SetJointForces(zeros); root.linearVelocity = Vector3.zero; root.angularVelocity = Vector3.zero;
            foreach (var rigidbody in demo.body.GetComponentsInChildren<Rigidbody>()) { rigidbody.linearVelocity = Vector3.zero; rigidbody.angularVelocity = Vector3.zero; }
            foreach (var leg in demo.body.Legs) if (leg != null) { leg.Coxa.SetTarget(0); leg.Femur.SetTarget(0); leg.Tibia.SetTarget(0); }
            var preset = demo.gameplayPreset;
            demo.controller.ConfigureFootAdhesion(true, preset.normalAdhesion, preset.shearAdhesion, preset.attachDelay, preset.detachThreshold);
            demo.controller.ReflexLayer?.ResetState(); demo.controller.SetPhaseForDiagnostics(baseline.phase); Physics.SyncTransforms();
            foreach (var leg in demo.body.Legs) if (leg != null && leg.FootContact != null) for (int i = 0; i < 3; i++) leg.FootContact.AdvanceAdhesionTick();
            report.physicsResetCount++; Log("physics_case_reset", null);
        }
        Transform Thorax => demo.body.Thorax == null ? demo.body.transform : demo.body.Thorax.transform;
        static double Now => Time.realtimeSinceStartupAsDouble;
        static string Argument(string key) { string[] args = Environment.GetCommandLineArgs(); int i = Array.IndexOf(args, key); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }
        static bool SafeId(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 64) return false;
            foreach (char c in value) if (!(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') && !(c >= '0' && c <= '9') && c != '_' && c != '-') return false;
            return true;
        }
        static bool IsAction(string value) => value == "STOP" || value == "FORWARD" || value == "TURN_R" || value == "TURN_L" || value == "FORWARD_R" || value == "FORWARD_L";
        static bool IsPlan(string value) => value == "nudge_right" || value == "nudge_left" || value == "right_then_forward" || value == "left_then_forward" || value == "forward_until_concern";
        static string SafeCode(string value) => string.IsNullOrEmpty(value) ? null : SafeId(value) ? value : "diagnostic_error";
        StreamWriter Writer(string name) => new StreamWriter(Path.Combine(outputDirectory, name), false, new UTF8Encoding(false)) { AutoFlush = true };
        void Log(string name, string fixtureId) => events?.WriteLine(JsonUtility.ToJson(new Entry { @event = name, realtimeSeconds = Now,
            caseId = current == null ? null : current.id, fixtureId = fixtureId, epoch = controller == null ? 0 : controller.ControlEpoch,
            generation = controller == null ? 0 : controller.ConversationGeneration, chunkIndex = chunkIndex, sampleCursor = sampleCursor }));
        void Save()
        {
            if (report == null || outputDirectory == null) return;
            // Explicit synthetic-input diagnostics only. Raw text never enters Control/events
            // or the operation path, and the default report continues to omit its contents.
            bool includeText = textDiagnosticsEnabled && controller != null
                && controller.FixtureInputEnabled && !controller.MicrophoneCapturing;
            foreach (Case item in report.cases)
                item.diagnosticTranscript = includeText ? item.recognizedText.ToString() : null;
            File.WriteAllText(Path.Combine(outputDirectory, "report.json"), JsonUtility.ToJson(report, true), new UTF8Encoding(false));
        }
        void Close() { events?.Dispose(); observations?.Dispose(); events = observations = null; }
        void OnDestroy()
        {
            if (controller != null) controller.ControlEventReceived -= OnControl;
            if (monitorSource != null) monitorSource.Stop();
            foreach (Fixture fixture in fixtures.Values)
                if (fixture.monitorClip != null) Destroy(fixture.monitorClip);
            if (monitorObject != null) Destroy(monitorObject);
            Close();
        }
    }
}
