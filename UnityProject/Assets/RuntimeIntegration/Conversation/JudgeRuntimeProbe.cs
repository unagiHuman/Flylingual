using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Flylingual.BlindSugarRun;
using Flylingual.PlayScreen;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

namespace Flylingual.Conversation
{
    // Explicit real-Player verification only; never supplies motor values or Brain frames.
    public sealed class JudgeRuntimeProbe : MonoBehaviour
    {
        string output;
        bool submission;
        float submissionDeadline;
        ConversationSessionController observed;
        readonly Dictionary<int, string> requested = new Dictionary<int, string>();
        int newestRequest, appliedRequest;
        string appliedAction;
        [Serializable] sealed class ControlResult
        { public string type, stage, action; public int requestId; }
        [Serializable] sealed class Gate
        {
            public string name, action, outcome = "not_run", reason;
            public bool applied, fresh, bodyObserved, idleResetObserved;
            public long firstSequence, lastSequence;
            public int firstEpoch, lastEpoch, requestId;
            public float seconds, displacement, yawDegrees;
        }

        [Serializable] sealed class Result
        {
            public string result = "startup_timeout", backend, error;
            public bool textSession, liveSession, brainReady, fresh, cloudFallback, stopped, cloudReplyReceived;
            public string questionTranscript;
            public bool submissionProbe, titlePresent, tutorialPresented, titleStarted;
            public bool warningObserved, escapedByMovement, swatterHit, gameOverUi, retryClicked, retryFresh;
            public bool fullCourseGoalVerified = false;
            public string unverified = "Full course goal, clean-machine and physical microphone are not verified.";
            public string runtimeVersion, operatingSystem, dataPath, initialScene;
            public int initialEpoch, finalEpoch, initialAttempt, retryAttempt;
            public float elapsedSeconds, swatterIdleSeconds, swatterWarningSeconds;
            public Gate[] gates;

            public long firstSequence, lastSequence;
            public float displacement;
            public string brainEndpoint = "127.0.0.1:18766";
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, "-judgeRuntimeProbe");
            if (i < 0 || i + 1 >= args.Length || FindAnyObjectByType<JudgeRuntimeProbe>() != null) return;
            var go = new GameObject("Judge runtime verification");
            DontDestroyOnLoad(go);
            var probe = go.AddComponent<JudgeRuntimeProbe>();
            probe.output = Path.GetFullPath(args[i + 1]);
            probe.submission = Array.IndexOf(args, "-judgeSubmissionProbe") >= 0;
        }

        void Capture(string json)
        {
            if (!json.Contains("command_result")) return;
            var e = JsonUtility.FromJson<ControlResult>(json);
            if (e == null || e.type != "command_result") return;
            if (e.stage == "submitted" && !string.IsNullOrEmpty(e.action))
            {
                requested[e.requestId] = e.action; newestRequest = Math.Max(newestRequest, e.requestId);
            }
            if (e.stage == "brain_applied" && requested.TryGetValue(e.requestId, out string action))
            { appliedRequest = e.requestId; appliedAction = action; }
        }

        void Bind(ConversationSessionController c)
        {
            if (observed == c) return;
            if (observed != null) observed.ControlEventReceived -= Capture;
            observed = c;
            requested.Clear(); newestRequest = appliedRequest = 0; appliedAction = null;
            if (observed != null) observed.ControlEventReceived += Capture;
        }

        bool WithinDeadline => Time.realtimeSinceStartup < submissionDeadline;
        static bool Healthy(ConversationSessionController c, BlindSugarRunSession stage)
            => c != null && stage != null && stage.fly != null && c.BodyControlActive
                && c.HasFreshBrain && stage.State == BlindSugarRunSession.StageState.Playing;

        IEnumerator ActionGate(Gate gate, string text, ConversationSessionController c, BlindSugarRunSession stage)
        {
            gate.firstSequence = c.Sequence; gate.firstEpoch = c.ControlEpoch;
            float started = Time.realtimeSinceStartup, until = Mathf.Min(submissionDeadline, started + 14f);
            int before = newestRequest;
            Vector3 initial = stage.fly.Position;
            c.SendPlayerText(text);
            float stable = 0, observedMotionAt = -1, last = Time.realtimeSinceStartup;
            while (WithinDeadline && Time.realtimeSinceStartup < until)
            {
                float now = Time.realtimeSinceStartup, delta = now - last; last = now;
                if (!Healthy(c, stage)) { gate.reason = "control_or_stage_unavailable"; break; }
                if (c.ControlEpoch != gate.firstEpoch) { gate.reason = "epoch_changed"; break; }
                if (appliedRequest > before && appliedAction == gate.action)
                { gate.applied = true; gate.requestId = appliedRequest; }
                Vector3 offset = stage.fly.Position - initial; offset.y = 0;
                gate.displacement = offset.magnitude;
                if (gate.applied)
                {
                    gate.yawDegrees += stage.fly.AngularVelocity.y * Mathf.Rad2Deg * delta;
                    if (gate.action == "STOP")
                    {
                        Vector3 velocity = stage.fly.LinearVelocity; velocity.y = 0;
                        stable = velocity.magnitude < .08f && Mathf.Abs(stage.fly.AngularVelocity.y) < .2f ? stable + delta : 0;
                        if (stable >= .5f) { gate.bodyObserved = true; break; }
                    }
                    else
                    {
                        bool moved = gate.action == "FORWARD" ? gate.displacement > .05f
                            : gate.action == "TURN_R" ? gate.yawDegrees > 1f : gate.yawDegrees < -1f;
                        if (moved && observedMotionAt < 0) observedMotionAt = now;
                        if (observedMotionAt >= 0 && now - observedMotionAt >= .15f)
                        { gate.bodyObserved = true; break; }
                    }
                }
                yield return null;
            }
            gate.seconds = Time.realtimeSinceStartup - started;
            gate.lastSequence = c.Sequence; gate.lastEpoch = c.ControlEpoch; gate.fresh = c.HasFreshBrain;
            gate.outcome = gate.applied && gate.bodyObserved && gate.fresh && gate.lastSequence > gate.firstSequence
                && gate.firstEpoch == gate.lastEpoch ? "pass" : "failed";
            if (gate.outcome != "pass" && string.IsNullOrEmpty(gate.reason)) gate.reason = "application_or_body_timeout";
        }

        IEnumerator RunSubmission(Result r)
        {
            float started = Time.realtimeSinceStartup;
            submissionDeadline = started + 300f;
            r.submissionProbe = true; r.runtimeVersion = Application.unityVersion;
            r.operatingSystem = SystemInfo.operatingSystem; r.dataPath = Application.dataPath;
            r.initialScene = SceneManager.GetActiveScene().path;
            var gates = new List<Gate>();
            TitleScreen title = null;
            while (WithinDeadline && Time.realtimeSinceStartup < started + 15f)
            {
                title = FindAnyObjectByType<TitleScreen>();
                if (title != null) break;
                yield return null;
            }
            r.titlePresent = title != null && TitleScreen.BlocksGameplay;
            if (r.titlePresent)
            {
                title.StartGame(); yield return null;
                r.tutorialPresented = TitleScreen.BlocksGameplay;
                if (TitleScreen.BlocksGameplay) { title.StartGame(); yield return null; }
                r.titleStarted = !TitleScreen.BlocksGameplay;
            }
            ConversationSessionController c = null;
            BlindSugarRunSession stage = null;
            while (r.titleStarted && WithinDeadline && Time.realtimeSinceStartup < started + 100f)
            {
                c = FindAnyObjectByType<ConversationSessionController>();
                stage = FindAnyObjectByType<BlindSugarRunSession>();
                if (Healthy(c, stage)) break;
                yield return new WaitForSecondsRealtime(.1f);
            }
            if (Healthy(c, stage) && r.titleStarted)
            {
                Bind(c);
                r.textSession = c.TextConversation; r.liveSession = c.ConversationLive;
                r.backend = c.Backend; r.brainReady = c.BrainReady;
                r.firstSequence = c.Sequence; r.initialEpoch = c.ControlEpoch; r.initialAttempt = stage.Attempt;
                string[] names = { "forward", "stop_after_forward", "right", "stop_after_right", "left", "stop_after_left", "move_again", "stop_before_warning" };
                string[] actions = { "FORWARD", "STOP", "TURN_R", "STOP", "TURN_L", "STOP", "FORWARD", "STOP" };
                string[] texts = { "前に進んで", "止まって", "右に曲がって", "止まって", "左に曲がって", "止まって", "前に進んで", "止まって" };
                bool controlsPassed = true;
                for (int i = 0; i < names.Length && WithinDeadline; i++)
                {
                    var gate = new Gate { name = names[i], action = actions[i] }; gates.Add(gate);
                    yield return ActionGate(gate, texts[i], c, stage);
                    if (gate.outcome != "pass") { controlsPassed = false; break; }
                }
                var swatter = stage.GetComponent<BlindSugarRunIdleSwatter>();
                if (controlsPassed && swatter != null)
                {
                    r.swatterIdleSeconds = swatter.idleSeconds; r.swatterWarningSeconds = swatter.warningSeconds;
                    // Diagnostic ceiling only; the game owns its warning and strike clocks.
                    float wait = Mathf.Min(submissionDeadline, Time.realtimeSinceStartup + 120f);
                    while (Healthy(c, stage) && !swatter.WarningActive && Time.realtimeSinceStartup < wait) yield return null;
                    r.warningObserved = swatter.WarningActive;
                    if (r.warningObserved)
                    {
                        Vector3 warningPosition = stage.fly.Position;
                        float warningIdleElapsed = swatter.IdleElapsed;
                        var escape = new Gate { name = "warning_escape", action = "FORWARD",
                            firstSequence = c.Sequence, firstEpoch = c.ControlEpoch }; gates.Add(escape);
                        int escapeBefore = newestRequest; float escapeStarted = Time.realtimeSinceStartup;
                        c.SendPlayerText("前に進んで");
                        while (WithinDeadline && Healthy(c, stage) && swatter.WarningActive && Time.realtimeSinceStartup < wait) yield return null;
                        Vector3 movement = stage.fly.Position - warningPosition; movement.y = 0;
                        // The game measures its idle anchor, not this warning-time position.
                        // Confirm its reset and use subsequent motion only as supporting evidence.
                        escape.idleResetObserved = swatter.IdleElapsed < warningIdleElapsed;
                        bool gameEscapeObserved = Healthy(c, stage) && swatter.Counting && !swatter.WarningActive
                            && !swatter.Struck && escape.idleResetObserved && c.ControlEpoch == escape.firstEpoch;
                        // The anchor can reset before this warning-relative displacement has accumulated.
                        // Keep observing the existing FORWARD; do not issue a replacement command.
                        float motionUntil = Mathf.Min(submissionDeadline, Time.realtimeSinceStartup + 2f);
                        while (gameEscapeObserved && WithinDeadline && Time.realtimeSinceStartup < motionUntil)
                        {
                            if (!Healthy(c, stage) || c.ControlEpoch != escape.firstEpoch
                                || swatter.Struck || swatter.WarningActive || !swatter.Counting)
                            { gameEscapeObserved = false; break; }
                            movement = stage.fly.Position - warningPosition; movement.y = 0;
                            if (movement.magnitude > .05f && c.Sequence > escape.firstSequence
                                && appliedRequest > escapeBefore && appliedAction == "FORWARD") break;
                            yield return null;
                        }
                        r.escapedByMovement = gameEscapeObserved && Healthy(c, stage)
                            && c.ControlEpoch == escape.firstEpoch && !swatter.Struck && !swatter.WarningActive
                            && swatter.Counting && movement.magnitude > .05f;
                        escape.displacement = movement.magnitude; escape.seconds = Time.realtimeSinceStartup - escapeStarted;
                        escape.lastSequence = c.Sequence; escape.lastEpoch = c.ControlEpoch; escape.fresh = c.HasFreshBrain;
                        escape.applied = appliedRequest > escapeBefore && appliedAction == "FORWARD";
                        escape.requestId = escape.applied ? appliedRequest : 0; escape.bodyObserved = r.escapedByMovement;
                        escape.outcome = r.escapedByMovement && escape.applied && escape.fresh
                            && escape.firstEpoch == escape.lastEpoch && escape.lastSequence > escape.firstSequence ? "pass" : "failed";
                        if (Healthy(c, stage))
                        {
                            var stop = new Gate { name = "stop_for_swatter", action = "STOP" }; gates.Add(stop);
                            yield return ActionGate(stop, "止まって", c, stage);
                        }
                    }
                    wait = Mathf.Min(submissionDeadline, Time.realtimeSinceStartup + 120f);
                    while (WithinDeadline && stage != null && stage.State == BlindSugarRunSession.StageState.Playing
                        && Time.realtimeSinceStartup < wait) yield return null;
                    r.swatterHit = swatter != null && swatter.Struck && stage.State == BlindSugarRunSession.StageState.GameOver;
                    r.gameOverUi = r.swatterHit && stage.OverlayVisible;
                    var view = stage.GetComponent<BlindSugarRunGameOverView>();
                    if (r.gameOverUi && view != null && view.RetryButton != null && view.RetryButton.enabledInHierarchy)
                    {
                        // Submit the real UI button; its handler owns BeginRetry and scene reload.
                        using (var submit = NavigationSubmitEvent.GetPooled()) view.RetryButton.SendEvent(submit);
                        r.retryClicked = stage.State == BlindSugarRunSession.StageState.Retrying;
                    }
                    wait = Mathf.Min(submissionDeadline, Time.realtimeSinceStartup + 55f);
                    while (r.retryClicked && WithinDeadline && Time.realtimeSinceStartup < wait)
                    {
                        stage = FindAnyObjectByType<BlindSugarRunSession>();
                        c = FindAnyObjectByType<ConversationSessionController>();
                        if (Healthy(c, stage) && stage.Attempt > r.initialAttempt) break;
                        yield return null;
                    }
                    r.retryFresh = Healthy(c, stage) && stage.Attempt > r.initialAttempt;
                    if (r.retryFresh)
                    {
                        Bind(c); r.retryAttempt = stage.Attempt;
                        var move = new Gate { name = "retry_forward", action = "FORWARD" }; gates.Add(move);
                        yield return ActionGate(move, "前に進んで", c, stage);
                        if (Healthy(c, stage))
                        {
                            var stop = new Gate { name = "retry_stop", action = "STOP" }; gates.Add(stop);
                            yield return ActionGate(stop, "止まって", c, stage);
                            r.stopped = stop.outcome == "pass";
                        }
                    }
                }
                r.lastSequence = c != null ? c.Sequence : -1; r.finalEpoch = c != null ? c.ControlEpoch : -1;
                r.fresh = c != null && c.HasFreshBrain; r.error = c != null ? c.Error : "controller_missing";
                r.result = r.titleStarted && controlsPassed && r.warningObserved && r.escapedByMovement
                    && r.swatterHit && r.gameOverUi && r.retryClicked && r.retryFresh && r.stopped
                    && gates.TrueForAll(g => g.outcome == "pass") ? "submission_path_pass" : "submission_path_failed";
            }
            else r.error = "normal_title_or_runtime_startup_failed";
            r.elapsedSeconds = Time.realtimeSinceStartup - started; r.gates = gates.ToArray();
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            File.WriteAllText(output, JsonUtility.ToJson(r, true));
            Bind(null);
            if (c != null) c.EmergencyStop();
            yield return new WaitForSecondsRealtime(1);
            Application.Quit();
        }

        IEnumerator Start()
        {
            var r = new Result();
            yield return null;
            if (submission) { yield return RunSubmission(r); yield break; }
            if (SceneManager.GetActiveScene().path != TitleScreen.InGameScenePath)
                yield return SceneManager.LoadSceneAsync(TitleScreen.InGameScenePath);
            ConversationSessionController c = null;
            BlindSugarRunSession stage = null;
            float deadline = Time.realtimeSinceStartup + 120;
            while (Time.realtimeSinceStartup < deadline)
            {
                c = FindAnyObjectByType<ConversationSessionController>();
                stage = FindAnyObjectByType<BlindSugarRunSession>();
                if (c != null && c.BodyControlActive && stage != null && stage.fly != null) break;
                yield return new WaitForSecondsRealtime(.2f);
            }
            if (c != null && c.BodyControlActive && stage != null && stage.fly != null)
            {
                r.textSession = c.TextConversation;
                r.liveSession = c.ConversationLive;
                r.backend = c.Backend;
                r.brainReady = c.BrainReady;
                r.firstSequence = c.Sequence;
                Vector3 initial = stage.fly.Position;
                c.SendPlayerText("前に進んで");
                yield return new WaitForSecondsRealtime(3);
                r.displacement = Vector3.Distance(initial, stage.fly.Position);
                c.SendPlayerText("止まって");
                yield return new WaitForSecondsRealtime(2);
                r.stopped = c.LastAppliedAction == "STOP";
                string beforeQuestion = c.Caption;
                c.SendPlayerText("宇宙について少し教えて");
                yield return new WaitForSecondsRealtime(6);
                r.cloudFallback = c.Caption.Contains("通信が使えない") || c.Caption.Contains("Cloud unavailable");
                r.questionTranscript = c.Caption.StartsWith(beforeQuestion) ? c.Caption.Substring(beforeQuestion.Length) : c.Caption;
                r.cloudReplyReceived = r.textSession && !r.cloudFallback && r.questionTranscript.Contains("assistant:");
                r.lastSequence = c.Sequence;
                r.fresh = c.HasFreshBrain;
                r.error = c.Error;
                r.result = c.ConversationActive && r.stopped && r.fresh && r.displacement > .05f
                    && r.lastSequence > r.firstSequence ? "control_pass" : "control_failed";
            }
            else if (c != null) r.error = c.Error;
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            File.WriteAllText(output, JsonUtility.ToJson(r, true));
            if (c != null) c.EmergencyStop();
            yield return new WaitForSecondsRealtime(1);
            Application.Quit();
        }
    }
}
