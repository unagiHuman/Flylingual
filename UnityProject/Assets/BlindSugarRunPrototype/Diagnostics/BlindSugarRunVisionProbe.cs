#if UNITY_EDITOR || DEVELOPMENT_BUILD
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Flylingual.Conversation;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Opt-in acceptance using the normal Windows Player, real Brain and live voice service.</summary>
    public sealed class BlindSugarRunVisionProbe : MonoBehaviour
    {
        [Serializable] public sealed class QuestionResult
        {
            public string question, caption;
            public bool acknowledged, actionsUnchanged;
            public float drift;
        }
        [Serializable] public sealed class Report
        {
            public string status = "RUNNING", phase = "startup", backend, runDirectory, error;
            public bool rawBrainReady, bodyActive, localVisionFresh, rangeBounded, explicitMoveObserved;
            public long firstSequence, lastSequence, sentObservations, observationAcks, replyAcks, audioBytes;
            public int freshSamples, samples;
            public float movedMeters;
            public float testIdleSeconds;
            public List<QuestionResult> questions = new List<QuestionResult>();
        }
        [Serializable] sealed class Event { public string type; public long sequence; }
        readonly Report report = new Report();
        ConversationSessionController controller;
        string directory;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-blindSugarVisionProbe") >= 0)
                new GameObject("Local Vision Acceptance Recorder").AddComponent<BlindSugarRunVisionProbe>();
        }

        IEnumerator Start()
        {
            var args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, "-blindSugarVisionProbe");
            if (index + 1 >= args.Length) yield break;
            directory = Path.GetFullPath(args[index + 1]); Directory.CreateDirectory(directory); Save();
            BlindSugarRunLocalVision vision = null;
            BlindSugarRunVisionPublisher publisher = null;
            BlindSugarRunSession stage = null;
            float until = Time.realtimeSinceStartup + 90;
            while (Time.realtimeSinceStartup < until)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                vision = FindAnyObjectByType<BlindSugarRunLocalVision>();
                publisher = FindAnyObjectByType<BlindSugarRunVisionPublisher>();
                stage = FindAnyObjectByType<BlindSugarRunSession>();
                // This opt-in conversation trial needs time for three answers without the 20s idle game rule.
                // Only the test instance's timer changes; body, terrain and Brain remain the normal ones.
                var swatter = stage == null ? null : stage.GetComponent<BlindSugarRunIdleSwatter>();
                if (swatter != null) { swatter.idleSeconds = 120; report.testIdleSeconds = 120; }
                if (controller != null && controller.BodyControlActive && controller.HasFreshBrain
                    && vision != null && vision.Fresh && publisher != null && publisher.SentObservations > 4) break;
                yield return null;
            }
            report.backend = controller?.Backend; report.rawBrainReady = controller != null && controller.BrainReady;
            report.runDirectory = FindAnyObjectByType<ConversationNativeBootstrap>()?.RunDirectory;
            report.bodyActive = controller != null && controller.BodyControlActive;
            report.localVisionFresh = vision != null && vision.Fresh;
            if (!report.bodyActive || !report.localVisionFresh || publisher == null || stage?.fly == null)
            { report.error = controller?.Error ?? "local_vision_or_body_unavailable"; Finish(false); yield break; }
            controller.ControlEventReceived += OnEvent;
            report.firstSequence = controller.Sequence;
            report.phase = "questions"; Save();
            // Let the connection/intro settle before checking that questions preserve the current Action.
            for (int i = 0; i < 20; i++) { Sample(); yield return new WaitForSecondsRealtime(.2f); }
            foreach (string question in new[] { "周りには何が見える？", "右は危ない？", "前に何がある？" })
            {
                int submitted = controller.SubmittedActions, applied = controller.LastAppliedRequestId;
                long ack = report.replyAcks;
                Vector3 position = stage.fly.Position;
                controller.SendPlayerText(question);
                for (int i = 0; i < 40; i++) { Sample(); yield return new WaitForSecondsRealtime(.2f); }
                report.questions.Add(new QuestionResult { question = question,
                    acknowledged = report.replyAcks > ack,
                    actionsUnchanged = controller.SubmittedActions == submitted && controller.LastAppliedRequestId == applied,
                    caption = controller.Caption, drift = Vector3.Distance(position, stage.fly.Position) });
                Save();
            }
            File.WriteAllText(Path.Combine(directory, "local-facts-before-walk.json"), JsonUtility.ToJson(vision.Facts, true));
            report.rangeBounded = true;
            foreach (var sector in vision.Facts.directions)
                report.rangeBounded &= sector.distance >= -1 && sector.distance <= 3 && sector.edgeDistance >= -1 && sector.edgeDistance <= 3;
            report.phase = "explicit_move"; Save();
            Vector3 from = stage.fly.Position;
            controller.SendPlayerText("前に1m進んで");
            until = Time.realtimeSinceStartup + 25;
            while (Time.realtimeSinceStartup < until && stage.State == BlindSugarRunSession.StageState.Playing)
            {
                Sample(); report.movedMeters = Vector3.ProjectOnPlane(stage.fly.Position - from, Vector3.up).magnitude;
                if (report.movedMeters > .5f && stage.fly.LinearVelocity.magnitude < .06f) break;
                yield return new WaitForSecondsRealtime(.2f);
            }
            report.explicitMoveObserved = report.movedMeters > .5f;
            File.WriteAllText(Path.Combine(directory, "local-facts-after-walk.json"), JsonUtility.ToJson(vision.Facts, true));
            report.sentObservations = publisher.SentObservations;
            report.audioBytes = controller.ReceivedNonzeroAudioBytes;
            report.lastSequence = controller.Sequence; report.error = controller.Error ?? controller.SchemaError;
            controller.EmergencyStop();
            bool questionsPassed = report.questions.Count == 3;
            foreach (var q in report.questions) questionsPassed &= q.acknowledged && q.actionsUnchanged;
            Finish(questionsPassed && report.observationAcks > 0 && report.rangeBounded && report.explicitMoveObserved
                && report.lastSequence > report.firstSequence && report.audioBytes > 0);
        }
        void OnEvent(string json)
        {
            var item = JsonUtility.FromJson<Event>(json);
            if (item?.type == "local_visual_observation_result") report.observationAcks++;
            if (item?.type == "local_visual_reply") report.replyAcks++;
        }
        void Sample() { report.samples++; if (controller.HasFreshBrain) report.freshSamples++; }
        void Save() { File.WriteAllText(Path.Combine(directory, "report.json"), JsonUtility.ToJson(report, true)); }
        void Finish(bool passed)
        {
            report.status = passed ? "PASS" : "FAIL"; report.phase = "done"; Save();
            if (controller != null) controller.ControlEventReceived -= OnEvent;
            Debug.Log("BLIND_SUGAR_VISION_PROBE " + report.status);
            Application.Quit(passed ? 0 : 4);
        }
    }
}
#endif
