using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using FlyBrainPoC;
using Flylingual.BlindSugarRun;
using FlyLocomotionPoC;
using FlyVisualDemo;
using Flylingual.PlayScreen;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>
    /// Opt-in synthetic-voice course pilot.  It observes the live body only to select the
    /// next bounded spoken direction; it never writes motor values, pose, physics, or rules.
    /// This is an automation oracle, not the blind player's information model.
    /// </summary>
    public sealed class SyntheticCoursePlayProbe : MonoBehaviour
    {
        [Serializable] sealed class Manifest { public int schemaVersion; public Fixture[] fixtures; }
        [Serializable] sealed class Fixture
        {
            public string id, file, sha256;
            [NonSerialized] public VoiceFixtureClip clip;
        }
        [Serializable] sealed class Sample
        {
            public double realtimeSeconds, elapsedSeconds;
            public string state, waypoint, requestedCommand, lastAction, fault, error;
            public int waypointIndex, epoch, generation;
            public long fixtureChunks, frameSequence;
            public bool bridgeReady, brainReady, bodyActive, freshBrain, insideGoal;
            public string backend;
            public Vector3 position;
            public float yawDegrees, goalDistance;
        }
        [Serializable] sealed class Report
        {
            public string result, reason, initialState, finalState, manifest;
            public bool bridgeReady, brainReady, bodyActive, brainFresh, fixtureInput, microphoneCapturing, goalInside;
            public string backend;
            public int waypointReached, epoch, generation;
            public long fixtureChunks, frameSequence;
            public double elapsedSeconds;
            public Vector3 initialPosition, finalPosition;
            public float initialYawDegrees, finalYawDegrees;
            public string controllerError, bodyFault;
            public List<string> missing = new List<string>();
        }
        [Serializable] sealed class ControlWire
        {
            public string type, @event, action, reason, error;
            public int requestId;
            public long sequence;
            public int epoch, conversationGeneration;
        }
        [Serializable] sealed class LifecycleRecord
        {
            public string type, @event, action, reason, error;
            public int requestId;
            public long sequence;
        }

        static readonly Vector3[] Route =
        {
            new Vector3(0f, 0f, 0f), new Vector3(0f, 0f, 29f), new Vector3(9f, 0f, 53f),
            new Vector3(9f, 0f, 65f), new Vector3(26.5f, 0f, 75f), new Vector3(34f, 0f, 87.5f),
            new Vector3(24f, 0f, 100f), new Vector3(5f, 0f, 102f)
        };
        static readonly string[] Names = { "start", "bridge-entry", "bridge-end", "book", "wide-1", "wide-2", "wide-3", "goal" };

        ConversationSessionController conversation;
        NativeConversationBody nativeBody;
        WindowsReplayDemo demo;
        BlindSugarRunSession stage;
        BlindSugarRunGoal goal;
        readonly Dictionary<string, Fixture> fixtures = new Dictionary<string, Fixture>(StringComparer.OrdinalIgnoreCase);
        StreamWriter progress, actions;
        string outputDirectory, manifestPath;
        Report report;
        int waypoint = 1;
        double startedAt, deadline, nextCommandAt, nextSampleAt;
        bool quit, finishing;
        int titleStartPresses;
        readonly Dictionary<int, string> submittedActions = new Dictionary<int, string>();
        int diagnosticAppliedCount;
        int diagnosticAppliedGeneration = -1;
        double diagnosticAppliedAt;
        string diagnosticAppliedAction, requestedCommand;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            string output = Argument("-flyCourseProbe");
            if (string.IsNullOrWhiteSpace(output)) return;
            new GameObject("Synthetic course voice play probe").AddComponent<SyntheticCoursePlayProbe>();
        }

        IEnumerator Start()
        {
            outputDirectory = Path.GetFullPath(Argument("-flyCourseProbe"));
            manifestPath = Argument("-flyVoiceFixtures");
            quit = Array.IndexOf(Environment.GetCommandLineArgs(), "-flyCourseProbeQuit") >= 0;
            Directory.CreateDirectory(outputDirectory);
            progress = new StreamWriter(Path.Combine(outputDirectory, "course-progress.jsonl"), false, new UTF8Encoding(false)) { AutoFlush = true };
            actions = new StreamWriter(Path.Combine(outputDirectory, "course-actions.jsonl"), false, new UTF8Encoding(false)) { AutoFlush = true };
            report = new Report { manifest = manifestPath };
            startedAt = Time.realtimeSinceStartupAsDouble;
            deadline = startedAt + 480d;
            try { LoadManifest(); }
            catch (Exception exception) { Finish("incomplete", "fixture_initialization_" + exception.GetType().Name); yield break; }

            // Enter through the public title-button route. A first-run tutorial requires the
            // same button a second time; the title owns cover, audio, time scale and safety.
            double titleDeadline = Math.Min(deadline, Time.realtimeSinceStartupAsDouble + 20d);
            while (TitleScreen.BlocksGameplay && Time.realtimeSinceStartupAsDouble < titleDeadline)
            {
                if (titleStartPresses < 2)
                {
                    TitleScreen title = FindAnyObjectByType<TitleScreen>();
                    if (title != null) { title.StartGame(); titleStartPresses++; }
                }
                yield return null;
            }
            if (TitleScreen.BlocksGameplay) { Finish("incomplete", "title_screen_blocked"); yield break; }

            // A bounded readiness wait, then the controller's normal STOP/start/resume handshake.
            double readyDeadline = Math.Min(deadline, Time.realtimeSinceStartupAsDouble + 30d);
            while (Time.realtimeSinceStartupAsDouble < readyDeadline)
            {
                Bind();
                if (conversation != null && (conversation.BodyControlActive || (conversation.Ready && conversation.FixtureInputEnabled
                    && conversation.VoiceActionsAvailable && conversation.OutputInhibited))) break;
                yield return null;
            }
            Bind();
            if (conversation == null || !conversation.Ready || !conversation.FixtureInputEnabled || !conversation.VoiceActionsAvailable)
            { Finish("incomplete", "voice_start_prerequisites_missing"); yield break; }
            if (!fixtures.ContainsKey("forward") || !fixtures.ContainsKey("left") || !fixtures.ContainsKey("right") || !fixtures.ContainsKey("stop"))
            { Finish("incomplete", "course_fixture_ids_missing"); yield break; }
            // Fixture tags are accepted only after the existing control-socket observation
            // opt-in. This is the same public setup used by NativeVoiceFixtureProbe.
            conversation.ControlEventReceived += OnControl;
            if (!conversation.EnableVoiceTestObservation()) { Finish("incomplete", "fixture_observation_not_enabled"); yield break; }

            if (!conversation.BodyControlActive) conversation.EnableVoiceActions();
            double armDeadline = Math.Min(deadline, Time.realtimeSinceStartupAsDouble + 40d);
            while (Time.realtimeSinceStartupAsDouble < armDeadline)
            {
                Bind();
                if (ReadyForCourse()) break;
                yield return null;
            }
            if (!ReadyForCourse()) { Finish("incomplete", "voice_control_not_ready"); yield break; }
            report.initialState = stage == null ? "missing" : stage.State.ToString();
            report.initialPosition = demo.body.Position;
            report.initialYawDegrees = Yaw;
            ScreenCapture.CaptureScreenshot(Path.Combine(outputDirectory, "course-begin.png"));
            nextSampleAt = Time.realtimeSinceStartupAsDouble;
            nextCommandAt = Time.realtimeSinceStartupAsDouble;

            while (!finishing && Time.realtimeSinceStartupAsDouble < deadline)
            {
                Bind();
                if (stage == null || goal == null || demo?.body == null || conversation == null || nativeBody == null)
                { Finish("incomplete", "scene_dependency_missing"); break; }
                if (stage.State == BlindSugarRunSession.StageState.GameOver || stage.State == BlindSugarRunSession.StageState.Interrupted)
                { Finish("failed", "stage_" + stage.State); break; }
                if (stage.State == BlindSugarRunSession.StageState.Goal || stage.State == BlindSugarRunSession.StageState.Reveal)
                { Finish("pass", "goal_state_" + stage.State); break; }
                if (FixtureDiagnosticError(out string fixtureError)) { Finish("incomplete", fixtureError); break; }
                if (!ReadyForCourse()) { Finish("incomplete", "live_control_lost"); break; }
                double now = Time.realtimeSinceStartupAsDouble;
                if (now >= nextSampleAt) { WriteSample(); nextSampleAt = now + 2d; }
                AdvanceWaypoint();
                if (now >= nextCommandAt) yield return Speak(SteeringCommand());
                else yield return null;
            }
            if (!finishing) Finish("incomplete", "course_timeout");
        }

        void LoadManifest()
        {
            if (string.IsNullOrWhiteSpace(manifestPath)) throw new ArgumentException("manifest_missing");
            manifestPath = Path.GetFullPath(manifestPath);
            string root = Path.GetDirectoryName(manifestPath);
            var manifest = JsonUtility.FromJson<Manifest>(File.ReadAllText(manifestPath));
            if (manifest == null || manifest.fixtures == null || manifest.fixtures.Length == 0) throw new InvalidDataException("manifest_invalid");
            foreach (Fixture fixture in manifest.fixtures)
            {
                if (fixture == null || string.IsNullOrEmpty(fixture.id) || string.IsNullOrEmpty(fixture.file)) continue;
                string path = Path.GetFullPath(Path.Combine(root, fixture.file));
                if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("fixture_outside_manifest");
                fixture.clip = VoiceFixtureClip.Load(path, fixture.sha256);
                string id = fixture.id.StartsWith("course-", StringComparison.OrdinalIgnoreCase) ? fixture.id.Substring(7) : fixture.id;
                if (id == "forward" || id == "left" || id == "right" || id == "stop") fixtures[id] = fixture;
            }
        }

        void Bind()
        {
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            if (nativeBody == null && conversation != null) nativeBody = conversation.GetComponent<NativeConversationBody>();
            if (demo == null) demo = FindAnyObjectByType<WindowsReplayDemo>();
            if (stage == null) stage = FindAnyObjectByType<BlindSugarRunSession>();
            if (goal == null) goal = FindAnyObjectByType<BlindSugarRunGoal>();
        }

        bool ReadyForCourse() => conversation != null && nativeBody != null && demo?.body != null
            && conversation.BodyControlActive && conversation.HasFreshBrain && nativeBody.BodyActive
            && string.IsNullOrEmpty(nativeBody.Fault) && conversation.FixtureInputTransmitting;

        void AdvanceWaypoint()
        {
            Vector3 position = demo.body.Position;
            while (waypoint < Route.Length - 1 && HorizontalDistance(position, Route[waypoint]) < 2.4f) waypoint++;
        }

        string SteeringCommand()
        {
            Vector3 delta = Route[waypoint] - demo.body.Position;
            delta.y = 0;
            float distance = delta.magnitude;
            if (waypoint == Route.Length - 1 && distance < 1.1f) return "stop";
            if (distance < .01f) return "stop";
            float desired = Mathf.Atan2(delta.x, delta.z) * Mathf.Rad2Deg;
            float error = Mathf.DeltaAngle(Yaw, desired);
            // Brief voice turns keep the existing action expiry and idle rule in charge.
            return Mathf.Abs(error) > 15f ? (error > 0 ? "right" : "left") : "forward";
        }

        IEnumerator Speak(string command)
        {
            if (!fixtures.TryGetValue(command, out Fixture fixture)) { Finish("incomplete", "missing_fixture_" + command); yield break; }
            int epoch = conversation.ControlEpoch, generation = conversation.ConversationGeneration;
            int appliedAtStart = diagnosticAppliedCount;
            requestedCommand = command;
            double commandStartedAt = Time.realtimeSinceStartupAsDouble;
            for (int index = 0; index < fixture.clip.Chunks.Length; index++)
            {
                if (FixtureDiagnosticError(out string chunkError)) { Finish("incomplete", chunkError); yield break; }
                if (!ReadyForCourse() || !conversation.TrySendFixturePcm(fixture.clip.Chunks[index], epoch, generation, fixture.id, index))
                { Finish("incomplete", "fixture_send_boundary_" + command); yield break; }
                yield return new WaitForSecondsRealtime(.1f);
            }
            // Wait for the same real voice delegation to apply before using the observed
            // position again, then leave its spoken bounded duration to the existing route.
            // This pilot deliberately does not infer a result from emitted audio alone.
            double appliedDeadline = Math.Min(deadline, Time.realtimeSinceStartupAsDouble + 8d);
            while (Time.realtimeSinceStartupAsDouble < appliedDeadline && ReadyForCourse()
                && (diagnosticAppliedCount == appliedAtStart || diagnosticAppliedAt < commandStartedAt
                    || diagnosticAppliedGeneration != generation || !ExpectedAction(command, diagnosticAppliedAction)))
                yield return null;
            if (stage != null && (stage.State == BlindSugarRunSession.StageState.Goal || stage.State == BlindSugarRunSession.StageState.Reveal))
            { Finish("pass", "goal_state_" + stage.State); yield break; }
            if (stage != null && (stage.State == BlindSugarRunSession.StageState.GameOver || stage.State == BlindSugarRunSession.StageState.Interrupted))
            { Finish("failed", "stage_" + stage.State); yield break; }
            if (FixtureDiagnosticError(out string fixtureError)) { Finish("incomplete", fixtureError); yield break; }
            if (!ReadyForCourse()) { Finish("incomplete", "voice_lost_while_waiting_" + command); yield break; }
            if (diagnosticAppliedCount == appliedAtStart) { Finish("incomplete", "voice_action_not_applied_" + command); yield break; }
            if (diagnosticAppliedAt < commandStartedAt || diagnosticAppliedGeneration != generation
                || !ExpectedAction(command, diagnosticAppliedAction))
            { Finish("incomplete", "voice_action_mismatch_" + command); yield break; }
            // No response remains visible in the report and is retried by the bounded pilot;
            // a successful command receives its full intended action time before re-steering.
            double motionSeconds = command == "forward" ? 3.25d : command == "stop" ? .75d : 1.35d;
            nextCommandAt = Time.realtimeSinceStartupAsDouble + motionSeconds;
        }

        void WriteSample()
        {
            var sample = new Sample
            {
                realtimeSeconds = Time.realtimeSinceStartupAsDouble, elapsedSeconds = Time.realtimeSinceStartupAsDouble - startedAt,
                state = stage == null ? "missing" : stage.State.ToString(), waypoint = Names[Mathf.Clamp(waypoint, 0, Names.Length - 1)], waypointIndex = waypoint,
                requestedCommand = requestedCommand, lastAction = diagnosticAppliedAction ?? conversation?.LastAppliedAction,
                fault = nativeBody?.Fault, error = conversation?.Error,
                epoch = conversation == null ? 0 : conversation.ControlEpoch, generation = conversation == null ? -1 : conversation.ConversationGeneration,
                fixtureChunks = conversation == null ? 0 : conversation.SentFixtureAudioChunks, frameSequence = FrameSequence,
                bridgeReady = conversation != null && conversation.Ready, brainReady = conversation != null && conversation.BrainReady,
                backend = conversation?.Backend, bodyActive = nativeBody != null && nativeBody.BodyActive,
                freshBrain = conversation != null && conversation.HasFreshBrain, insideGoal = goal != null && goal.InsideGoal,
                position = demo?.body == null ? Vector3.zero : demo.body.Position, yawDegrees = Yaw,
                goalDistance = demo?.body == null ? -1f : HorizontalDistance(demo.body.Position, Route[Route.Length - 1])
            };
            progress.WriteLine(JsonUtility.ToJson(sample));
        }

        void OnControl(string json)
        {
            ControlWire item;
            try { item = JsonUtility.FromJson<ControlWire>(json); }
            catch { return; }
            if (item == null || !AllowedLifecycle(item.type) && !AllowedLifecycle(item.@event)) return;
            // This intentionally retains no transcription, fixture PCM, input IDs or raw event.
            actions?.WriteLine(JsonUtility.ToJson(new LifecycleRecord { type = item.type, @event = item.@event,
                action = item.action, requestId = item.requestId, sequence = item.sequence, reason = item.reason, error = item.error }));
            // The event is received on the current sole control socket; constrain its epoch
            // and observe the controller's current generation at receipt, rather than trust a
            // missing optional payload generation.
            if (item.type != "voice_test_diagnostic" || conversation == null || item.epoch != conversation.ControlEpoch) return;
            if (item.@event == "command_submitted" && item.requestId > 0 && !string.IsNullOrEmpty(item.action))
                submittedActions[item.requestId] = item.action;
            if (item.@event == "command_applied" && item.requestId > 0)
            {
                string action = item.action;
                if (string.IsNullOrEmpty(action)) submittedActions.TryGetValue(item.requestId, out action);
                if (!string.IsNullOrEmpty(action))
                {
                    diagnosticAppliedAction = action;
                    diagnosticAppliedAt = Time.realtimeSinceStartupAsDouble;
                    diagnosticAppliedGeneration = conversation.ConversationGeneration;
                    diagnosticAppliedCount++;
                }
            }
        }

        static bool AllowedLifecycle(string value) => value == "command_submitted" || value == "command_applied"
            || value == "command_expired" || value == "intent_classified" || value == "error";
        static bool ExpectedAction(string command, string action) => (command == "forward" && action == "FORWARD")
            || (command == "left" && action == "TURN_L") || (command == "right" && action == "TURN_R")
            || (command == "stop" && action == "STOP");

        long FrameSequence
        {
            get
            {
                if (demo?.client != null && demo.client.TryGetLatestFrame(out BrainFrame frame, out double unused) && frame != null) return frame.sequence;
                return conversation == null ? -1 : conversation.Sequence;
            }
        }
        float Yaw => demo?.body == null ? 0f : (demo.body.Thorax == null ? demo.body.transform.eulerAngles.y : demo.body.Thorax.transform.eulerAngles.y);
        bool FixtureDiagnosticError(out string reason)
        {
            string error = conversation == null ? null : (conversation.SchemaError ?? conversation.Error ?? conversation.AudioError);
            if (!string.IsNullOrEmpty(error) && error.IndexOf("fixture", StringComparison.OrdinalIgnoreCase) >= 0)
            { reason = "fixture_diagnostic_" + error; return true; }
            reason = null;
            return false;
        }
        static float HorizontalDistance(Vector3 a, Vector3 b) { a.y = b.y = 0; return Vector3.Distance(a, b); }
        static string Argument(string key) { string[] args = Environment.GetCommandLineArgs(); int i = Array.IndexOf(args, key); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }

        void Finish(string result, string reason)
        {
            if (finishing) return;
            finishing = true;
            Bind();
            report.result = result; report.reason = reason;
            report.finalState = stage == null ? "missing" : stage.State.ToString();
            report.bridgeReady = conversation != null && conversation.Ready; report.brainReady = conversation != null && conversation.BrainReady;
            report.backend = conversation?.Backend; report.bodyActive = nativeBody != null && nativeBody.BodyActive;
            report.brainFresh = conversation != null && conversation.HasFreshBrain; report.fixtureInput = conversation != null && conversation.FixtureInputEnabled;
            report.microphoneCapturing = conversation != null && conversation.MicrophoneCapturing; report.goalInside = goal != null && goal.InsideGoal;
            report.waypointReached = waypoint; report.epoch = conversation == null ? 0 : conversation.ControlEpoch; report.generation = conversation == null ? -1 : conversation.ConversationGeneration;
            report.fixtureChunks = conversation == null ? 0 : conversation.SentFixtureAudioChunks; report.frameSequence = FrameSequence;
            report.elapsedSeconds = Time.realtimeSinceStartupAsDouble - startedAt; report.finalPosition = demo?.body == null ? Vector3.zero : demo.body.Position; report.finalYawDegrees = Yaw;
            report.controllerError = conversation?.Error; report.bodyFault = nativeBody?.Fault;
            if (conversation == null) report.missing.Add("conversation"); if (nativeBody == null) report.missing.Add("native_body");
            if (demo?.body == null) report.missing.Add("live_body"); if (stage == null) report.missing.Add("stage"); if (goal == null) report.missing.Add("goal");
            if (conversation != null && !conversation.FixtureInputEnabled) report.missing.Add("fixture_input_disabled");
            WriteSample();
            ScreenCapture.CaptureScreenshot(Path.Combine(outputDirectory, "course-end.png"));
            File.WriteAllText(Path.Combine(outputDirectory, "report.json"), JsonUtility.ToJson(report, true), new UTF8Encoding(false));
            progress?.Dispose(); progress = null;
            if (conversation != null) conversation.ControlEventReceived -= OnControl;
            actions?.Dispose(); actions = null;
            conversation?.StopConversation();
            if (quit) StartCoroutine(QuitAfterScreenshot(result == "pass" ? 0 : 2));
        }

        IEnumerator QuitAfterScreenshot(int exitCode)
        {
            // CaptureScreenshot writes at end of frame. Keep the player alive through that
            // frame so the terminal image is an artifact rather than a queued request.
            yield return new WaitForEndOfFrame();
            yield return new WaitForSecondsRealtime(.2f);
            Application.Quit(exitCode);
        }

        void OnDestroy()
        {
            if (conversation != null) conversation.ControlEventReceived -= OnControl;
            progress?.Dispose(); actions?.Dispose();
        }
    }
}
