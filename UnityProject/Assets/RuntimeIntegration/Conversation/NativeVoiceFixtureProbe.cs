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
    public sealed class NativeVoiceFixtureProbe : MonoBehaviour
    {
        [Serializable] sealed class Manifest { public int schemaVersion; public Fixture[] fixtures; }
        [Serializable] sealed class Fixture
        {
            public string id, file, sha256, expectedAction, utterance, expectedKind, expectedPlan;
            public double durationSeconds;
            [NonSerialized] public VoiceFixtureClip clip;
        }
        [Serializable] sealed class Control
        {
            public string type, @event, stage, commandId, delegationId, fixtureId, action, source, kind;
            public string plan, planId, name, outcome, reason, state, owner, sessionId, instanceId;
            public int epoch, conversationGeneration, requestId, fixtureChunkIndex, step;
            public long sequence;
            public double monotonicMs, audioStartMs, audioEndMs, startMs, endMs, offsetMs;
            public double interpretationMs, proposalValidForMs;
            public bool continuedListening, outputInhibited;
            [NonSerialized] public double localTime;
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
            public string actualKind, actualAction, actualPlan, commandId, delegationId, planId;
            public string status = "pending", error, correlation = "unconfirmed";
            public int epoch, generation, requestId, sentChunks, observedSamples;
            public long appliedSequence, sourceSampleStart, sourceSampleEnd;
            public double startedAt, firstAudioAt = -1, lastAudioAt = -1, appliedAt = -1, endedAt;
            public double bridgeAudioStartMs = -1, bridgeAudioEndMs = -1;
            public double durationSeconds;
            public int sourceSampleRate, sourceChannels;
            public double delegationStartMs, delegationEndMs, delegationOffsetMs;
            public double fixtureToAppliedMs, fixtureToBodyStartedMs, fixtureToSettledMs;
            public bool applied, bodyStarted, settled, expired, continuedListening, voiceStopBeforeExpiry;
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
        }
        [Serializable] sealed class Report
        {
            public string result = "incomplete", status = "incomplete", suite, inputSource = "synthetic_fixture";
            public string manifest, manifestSha256, error, backend, brainSessionId, brainInstanceId;
            public bool pass, brainReady, microphoneTested, startupFreshStop, overlapVerified;
            public bool stopped, controllerReleasedObserved, bridgeStoppedObserved, protocolShutdownObserved, processCleanupObserved;
            public int ttlReacceptChecks, physicsResetCount;
            public long sentFixtureAudioChunks, sentPcmSamples;
            public double startedAt, endedAt, requestedSeconds, minSendIntervalMs, maxSendIntervalMs;
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
        bool running, quit, observationEnabled;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
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
            controller.ControlEventReceived += OnControl;
            observationEnabled = controller.EnableVoiceTestObservation();
            if (!controller.FixtureInputEnabled || !observationEnabled)
            { yield return FinishRun("fixture_observation_unavailable"); yield break; }
            running = true;
            nextAudioAt = Now;
            while (Now < startupDeadline && !CanObserve()) yield return null;
            if (!CanObserve()) { yield return FinishRun("fresh_live_control_unavailable"); yield break; }
            report.backend = controller.Backend;
            report.brainReady = controller.BrainReady;
            report.brainSessionId = controller.BrainSessionId;
            report.brainInstanceId = controller.BrainInstanceId;
            bool initialStop = false;
            yield return WaitStopped(20, value => initialStop = value);
            report.startupFreshStop = initialStop;
            if (!initialStop) { yield return FinishRun("startup_stop_not_observed"); yield break; }
            CaptureBaseline();

            if (report.suite == "plans") yield return RunPlans();
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
            yield return FinishRun(report.error);
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

        bool Initialize()
        {
            quit = Array.IndexOf(Environment.GetCommandLineArgs(), "-flyVoiceFixtureQuit") >= 0;
            try
            {
                string path = Path.GetFullPath(Argument("-flyVoiceFixtures"));
                outputDirectory = Argument("-flyVoiceFixtureOutput");
                if (string.IsNullOrWhiteSpace(outputDirectory)) throw new ArgumentException("output_directory_required");
                outputDirectory = Path.GetFullPath(outputDirectory);
                Directory.CreateDirectory(outputDirectory);
                if (File.Exists(Path.Combine(outputDirectory, "report.json"))) throw new ArgumentException("output_already_contains_report");
                string suite = Argument("-flyVoiceFixtureSuite") ?? "smoke";
                if (suite != "smoke" && suite != "full" && suite != "soak" && suite != "plans") throw new ArgumentException("invalid_suite");
                double seconds = suite == "full" ? 900 : suite == "soak" ? 300 : 240;
                string duration = Argument("-flyVoiceFixtureSeconds");
                if (duration != null && (!double.TryParse(duration, NumberStyles.Float, CultureInfo.InvariantCulture, out seconds)
                    || double.IsNaN(seconds) || double.IsInfinity(seconds) || seconds < 1 || seconds > 3600)) throw new ArgumentException("invalid_duration");
                report = new Report { suite = suite, manifest = path, startedAt = Now, requestedSeconds = seconds };
                using (var sha = SHA256.Create()) report.manifestSha256 = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-", "").ToLowerInvariant();
                deadline = Now + seconds;
                events = Writer("events.jsonl"); observations = Writer("observations.jsonl");
                Manifest manifest = JsonUtility.FromJson<Manifest>(File.ReadAllText(path));
                if (manifest == null || manifest.schemaVersion != 1 || manifest.fixtures == null || manifest.fixtures.Length == 0)
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
                    if (fixture.expectedKind != "action" && fixture.expectedKind != "plan") throw new ArgumentException("invalid_expected_kind");
                    if (fixture.expectedKind == "action" && !IsAction(fixture.expectedAction)) throw new ArgumentException("invalid_expected_action");
                    if (fixture.expectedKind == "plan" && !IsPlan(fixture.expectedPlan)) throw new ArgumentException("invalid_expected_plan");
                    fixtures.Add(fixture.id, fixture);
                }
                string[] required = suite == "plans" ? Array.Empty<string>() : suite == "full"
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
            if (previousAudioAt >= 0)
            {
                double intervalMs = (sendStarted - previousAudioAt) * 1000;
                report.maxSendIntervalMs = Math.Max(report.maxSendIntervalMs, intervalMs);
                report.minSendIntervalMs = report.minSendIntervalMs <= 0 ? intervalMs : Math.Min(report.minSendIntervalMs, intervalMs);
            }
            previousAudioAt = sendStarted; nextAudioAt += .1; audioNotBefore = sendStarted + .09;
            if (playing != null)
            {
                if (chunkIndex == 0) { current.firstAudioAt = Now; current.sourceSampleStart = sampleCursor; Log("fixture_audio_started", id); }
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

        void OnControl(string json)
        {
            Control item;
            try { item = JsonUtility.FromJson<Control>(json); }
            catch (ArgumentException) { return; }
            if (item == null) return;
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
            if (item.type == "voice_test_diagnostic")
            {
                controls.Add(item);
                if (item.@event == "delegation_observed" && !string.IsNullOrEmpty(item.delegationId)) delegations[item.delegationId] = item;
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
            if (item.@event == "voice_intent_dispatch" && item.outcome == "started")
            {
                if (current.firstAudioAt < 0) return;
                if (string.IsNullOrEmpty(current.commandId)) { current.commandId = item.commandId; current.delegationId = item.delegationId; }
                else if (current.commandId != item.commandId) Fail(current, "multiple_delegations_for_fixture");
            }
            if (item.commandId == current.commandId && !string.IsNullOrEmpty(current.commandId))
            {
                current.lifecycle.Add(item);
                if (item.@event == "intent_classified") { current.actualKind = item.kind; current.actualAction = item.action; current.actualPlan = item.plan; }
                if (item.@event == "intent_rejected") Fail(current, SafeCode(item.reason));
                if (item.@event == "command_applied")
                {
                    current.applied = true; current.appliedAt = Now;
                    current.requestId = item.requestId; current.appliedSequence = item.sequence;
                    current.fixtureToAppliedMs = (Now - current.firstAudioAt) * 1000;
                }
                if (item.@event == "plan_started") current.planId = item.planId;
            }
            if (!string.IsNullOrEmpty(current.planId) && item.planId == current.planId) current.lifecycle.Add(item);
            Correlate(current);
        }

        void Correlate(Case item)
        {
            if (string.IsNullOrEmpty(item.delegationId) || !delegations.TryGetValue(item.delegationId, out Control delegation)) return;
            item.delegationStartMs = delegation.startMs; item.delegationEndMs = delegation.endMs; item.delegationOffsetMs = delegation.offsetMs;
            if (item.bridgeAudioStartMs >= 0 && item.bridgeAudioEndMs > item.bridgeAudioStartMs
                && delegation.endMs > item.bridgeAudioStartMs && delegation.startMs < item.bridgeAudioEndMs)
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
                item.actualForwardPeak = Mathf.Max(item.actualForwardPeak, Mathf.Abs(frame.motor.forward));
                item.actualTurnPeak = Mathf.Max(item.actualTurnPeak, Mathf.Abs(frame.motor.turn));
                if (item.applied && age <= .75 && MatchesApplied(frame, item.appliedSequence, item.requestId,
                    item.brainSessionId, item.brainInstanceId, item.actualAction)) ObservePostApplied(item, frame);
                if (item.applied && frame.sequence >= item.appliedSequence && !item.bodyStarted
                    && MovementPassed(item))
                { item.bodyStarted = true; item.fixtureToBodyStartedMs = (Now - item.firstAudioAt) * 1000; Log("body_started", item.fixtureId); }
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
            if (item.status == "pending") item.status = passed && string.IsNullOrEmpty(item.error) && item.applied
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
            report.pass = string.IsNullOrEmpty(error) && report.cases.Count > 0 && report.cases.TrueForAll(x => x.status == "pass")
                && report.ttlReacceptChecks >= 3 && report.overlapVerified;
            if (string.IsNullOrEmpty(report.error) && !report.overlapVerified) report.error = "reply_overlap_not_observed";
            report.status = report.pass ? "pass" : report.cases.Exists(x => x.status == "blocked") ? "blocked" : "incomplete";
            report.result = report.pass ? "native_voice_fixture_pass" : report.status;
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
        void Save() { if (report != null && outputDirectory != null) File.WriteAllText(Path.Combine(outputDirectory, "report.json"), JsonUtility.ToJson(report, true), new UTF8Encoding(false)); }
        void Close() { events?.Dispose(); observations?.Dispose(); events = observations = null; }
        void OnDestroy() { if (controller != null) controller.ControlEventReceived -= OnControl; Close(); }
    }
}
