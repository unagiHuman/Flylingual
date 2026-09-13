using System;
using System.Collections.Generic;
using Flylingual.Conversation;
using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Local observations to the existing control socket. No motor or game-state authority.</summary>
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunNarrator : MonoBehaviour
    {
        BlindSugarRunSession stage;
        ConversationSessionController conversation;
        FlyTerrainSensor sensor;
        readonly HashSet<string> once = new HashSet<string>();
        string runId, lastObservation, previousAction;
        int generation = -1, epoch = -1;
        long sequence;
        float nextSpeech, stableSince = -1f;
        string lastGround = "unknown", lastLeft = "unknown", lastRight = "unknown";
        float lastGroundAt = float.NegativeInfinity;
        bool observedMovement;
        bool rulerAnnounced;
        string lastRulerAlignment;
        long introSequence, firstIntroSequence;
        bool subscribed;
        bool goalWanted, revealWanted;
        float goalDeadline, revealDeadline;
        long firstGoalSequence, lastGoalSequence, firstRevealSequence, lastRevealSequence;
        public bool GoalAcknowledged { get; private set; }
        public bool RevealAcknowledged { get; private set; }
        public long SentCues { get; private set; }
        public string LastCue { get; private set; }

        void Awake() { stage = GetComponent<BlindSugarRunSession>(); }

        void Update()
        {
            if (stage == null || stage.fly == null) return;
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            if (conversation == null) return;
            if (!subscribed) { conversation.ControlEventReceived += OnControlEvent; subscribed = true; }
            if (!conversation.ConversationLive || generation != conversation.ConversationGeneration)
            {
                ResetContext();
                generation = conversation.ConversationGeneration;
                epoch = conversation.ControlEpoch;
            }
            // The Bridge run/sequence is conversation-scoped. An epoch change discards local observations only.
            if (epoch != conversation.ControlEpoch)
            {
                epoch = conversation.ControlEpoch; lastObservation = null; lastGroundAt = float.NegativeInfinity;
                lastGround = lastLeft = lastRight = "unknown";
                stableSince = -1f; observedMovement = false; previousAction = null;
                rulerAnnounced = false; lastRulerAlignment = null;
                ClearMilestones();
            }
            if (stage.State == BlindSugarRunSession.StageState.Goal || stage.State == BlindSugarRunSession.StageState.Reveal)
            { SendMilestones(); return; }
            if (stage.State != BlindSugarRunSession.StageState.Playing) return;
            if (!conversation.BodyControlActive || !conversation.BlindRunScriptAvailable) return;
            if (runId == null) runId = Guid.NewGuid().ToString("N");
            if (!once.Contains("intro"))
            {
                if (Time.unscaledTime >= nextSpeech && Send("intro", "{\"stageStarted\":true}", 0))
                { introSequence = sequence; if (firstIntroSequence == 0) firstIntroSequence = sequence; }
                return;
            }
            if (sensor == null) sensor = stage.fly.GetComponent<FlyTerrainSensor>();
            var o = sensor == null ? null : sensor.Observation;
            bool fresh = sensor != null && sensor.Fresh && o != null && !o.queryOverflow;
            if (fresh && o.groundPresent)
            {
                lastGround = Ground(o.ground.surface); lastLeft = o.leftEdge; lastRight = o.rightEdge;
                lastGroundAt = o.sampledAt;
            }
            if (fresh)
            {
                float age = Mathf.Max(0, (Time.unscaledTime - o.sampledAt) * 1000f);
                // Urgent local hazards take priority over tutorial and normal observations.
                if (o.rightEdge == "very_near") { Observe("right_edge_urgent", "{\"rightEdge\":\"very_near\"}", age, true); return; }
                if (o.leftEdge == "very_near") { Observe("left_edge_urgent", "{\"leftEdge\":\"very_near\"}", age, true); return; }
                if (Once("vision", "{\"externalVisionAvailable\":true}", age)) return;
            }
            if (once.Contains("vision") && Once("ask", "{\"tutorialPrompt\":true}")) return;
            // One initial practice prompt; later lessons require observed applied Action progress.
            if (once.Contains("ask") && Once("forward_lesson", "{\"tutorialPrompt\":true}")) return;
            string action = conversation.LastAppliedAction;
            if (action == "FORWARD" && Once("turn_lesson", "{\"tutorialPrompt\":true}")) return;
            if ((action == "TURN_L" || action == "TURN_R") && Once("stop_lesson", "{\"tutorialPrompt\":true}")) return;
            if (!fresh) { stableSince = -1f; return; }
            float observedAge = Mathf.Max(0, (Time.unscaledTime - o.sampledAt) * 1000f);
            if (o.rightEdge == "near" && Observe("right_edge", "{\"rightEdge\":\"near\"}", observedAge)) return;
            if (o.leftEdge == "near" && Observe("left_edge", "{\"leftEdge\":\"near\"}", observedAge)) return;
            if (ReportLocalRuler(o)) return;
            if (o.groundPresent && Ground(o.ground.surface) == "book" && Observe("book", "{\"ground\":\"book\"}", observedAge)) return;
            bool moving = stage.fly.LinearVelocity.magnitude > .03f || stage.fly.AngularVelocity.magnitude > .08f;
            if (moving) { observedMovement = true; stableSince = -1f; }
            else if (!o.groundPresent || o.bodyUnsafe) stableSince = -1f;
            else if (stableSince < 0) stableSince = Time.unscaledTime;
            if (action == "STOP" && moving && previousAction != "STOP")
                Observe("still_moving", "{\"bodyMoving\":true}", 0);
            if (observedMovement && stableSince >= 0 && Time.unscaledTime - stableSince >= 1f)
            {
                if (Observe("stable", "{\"bodyMoving\":false,\"bodyStable\":true}", 0)) observedMovement = false;
            }
            previousAction = action;
        }

        void ResetContext()
        {
            runId = null; once.Clear(); lastObservation = null; nextSpeech = 0;
            lastGround = lastLeft = lastRight = "unknown"; lastGroundAt = float.NegativeInfinity;
            stableSince = -1f; observedMovement = false; previousAction = null;
            rulerAnnounced = false; lastRulerAlignment = null;
            introSequence = firstIntroSequence = 0;
            ClearMilestones();
        }

        void ClearMilestones()
        {
            goalWanted = revealWanted = GoalAcknowledged = RevealAcknowledged = false;
            firstGoalSequence = lastGoalSequence = firstRevealSequence = lastRevealSequence = 0;
        }

        void SendMilestones()
        {
            float now = Time.unscaledTime;
            if (now < nextSpeech) return;
            if (goalWanted && !GoalAcknowledged && now <= goalDeadline)
            {
                if (Send("goal", "{\"insideGoal\":true,\"bodyStable\":true,\"goalConfirmed\":true}", 0))
                { lastGoalSequence = sequence; if (firstGoalSequence == 0) firstGoalSequence = sequence; }
                return;
            }
            if (revealWanted && GoalAcknowledged && !RevealAcknowledged && now <= revealDeadline)
            {
                if (Send("reveal", "{\"revealStarted\":true}", 0))
                { lastRevealSequence = sequence; if (firstRevealSequence == 0) firstRevealSequence = sequence; }
            }
        }

        bool ReportLocalRuler(FlyWorldObservation observation)
        {
            if (!observation.groundPresent || observation.bodyUnsafe) return false;
            // Two downward probes ahead, bounded by the existing sensor's local reach.
            // Only the hit collider is classified; no scene, route, anchor, or map lookup.
            for (int i = 0; i < 2; i++)
            {
                Vector3 up = sensor.Up;
                Vector3 origin = stage.fly.Position + sensor.Forward * sensor.Reach * (i == 0 ? .75f : 1.5f);
                float top = Vector3.Dot(observation.ground.point, up) + sensor.MaximumStep + sensor.Reach * .25f;
                origin += up * (top - Vector3.Dot(origin, up));
                if (!sensor.Cast(origin, -up, sensor.Reach * 2f, 0, out var hit)
                    || observation.queryOverflow || hit.collider.name != "RulerBridge") continue;
                if (!rulerAnnounced)
                {
                    if (!Observe("ruler_ahead", "{\"forwardObject\":\"ruler\"}", 0)) return false;
                    rulerAnnounced = true;
                    return true;
                }
                var box = hit.collider as BoxCollider;
                if (box == null) return false; // Unknown shape: do not infer its alignment.
                Vector3 x = Vector3.ProjectOnPlane(box.transform.TransformVector(Vector3.right * box.size.x), up);
                Vector3 z = Vector3.ProjectOnPlane(box.transform.TransformVector(Vector3.forward * box.size.z), up);
                if (Mathf.Min(x.magnitude, z.magnitude) <= .0001f
                    || Mathf.Max(x.magnitude, z.magnitude) < Mathf.Min(x.magnitude, z.magnitude) * 1.5f) return false;
                Vector3 axis = x.sqrMagnitude > z.sqrMagnitude ? x.normalized : z.normalized;
                if (Vector3.Dot(axis, sensor.Forward) < 0) axis = -axis;
                float angle = Vector3.SignedAngle(sensor.Forward, axis, up);
                // Nearly transverse boards are outside the script's "a little left/right" wording.
                if (Mathf.Abs(angle) > 45f) return false;
                string alignment = Mathf.Abs(angle) <= 8f ? "center" : angle > 0 ? "right" : "left";
                if (alignment == lastRulerAlignment) return false;
                string cue = alignment == "center" ? "aligned" : "ruler_" + alignment;
                if (!Observe(cue, "{\"forwardObject\":\"ruler\",\"alignment\":\"" + alignment + "\"}", 0)) return false;
                lastRulerAlignment = alignment;
                return true;
            }
            rulerAnnounced = false; lastRulerAlignment = null;
            return false;
        }

        void OnControlEvent(string json)
        {
            var result = JsonUtility.FromJson<CueResult>(json);
            if (result == null || result.type != "blind_run_cue_result" || result.stage != "queued"
                || !conversation.ConversationLive || generation != conversation.ConversationGeneration
                || epoch != conversation.ControlEpoch) return;
            if (firstIntroSequence > 0 && result.sequence >= firstIntroSequence && result.sequence <= introSequence) once.Add("intro");
            if (firstGoalSequence > 0 && result.sequence >= firstGoalSequence && result.sequence <= lastGoalSequence) GoalAcknowledged = true;
            if (firstRevealSequence > 0 && result.sequence >= firstRevealSequence && result.sequence <= lastRevealSequence) RevealAcknowledged = true;
        }
        void OnDestroy() { if (conversation != null && subscribed) conversation.ControlEventReceived -= OnControlEvent; }
        [Serializable] sealed class CueResult { public string type, stage; public long sequence; }

        bool Once(string cue, string evidence, float age = 0)
        {
            if (once.Contains(cue) || Time.unscaledTime < nextSpeech) return false;
            if (!Send(cue, evidence, age)) return false;
            once.Add(cue); return true;
        }
        bool Observe(string cue, string evidence, float age, bool urgent = false)
        {
            if (lastObservation == cue || (!urgent && Time.unscaledTime < nextSpeech)) return false;
            if (!Send(cue, evidence, age)) return false;
            lastObservation = cue; return true;
        }
        bool Send(string cue, string evidence, float age)
        {
            if (runId == null || conversation == null || !once.Contains("intro") && cue != "intro") return false;
            // A new voice generation starts a new run, even after a scene retry. Never restore fall memory.
            if (generation != conversation.ConversationGeneration || epoch != conversation.ControlEpoch) return false;
            if (!conversation.TrySendBlindRunCue(runId, 1, sequence + 1, cue, evidence, age)) return false;
            sequence++; SentCues++; LastCue = cue; nextSpeech = Time.unscaledTime + 3.25f;
            return true;
        }

        public void NotifyFall(bool healthy, string appliedAction)
        {
            if (!healthy) { Send("link_error", "{\"technicalFault\":true}", 0); return; }
            if (!ValidAction(appliedAction)) return;
            bool fresh = Time.unscaledTime - lastGroundAt <= .75f;
            var evidence = new FallEvidence { ground = fresh ? lastGround : "unknown", lastAction = appliedAction,
                leftEdge = fresh ? lastLeft : "unknown", rightEdge = fresh ? lastRight : "unknown" };
            Send("fall", JsonUtility.ToJson(evidence), 0);
        }

        public bool NotifyGoalConfirmed(bool insideGoal, bool bodyStable, bool goalConfirmed)
        {
            if (!insideGoal || !bodyStable || !goalConfirmed || stage == null || stage.State != BlindSugarRunSession.StageState.Goal
                || conversation == null || generation != conversation.ConversationGeneration || epoch != conversation.ControlEpoch) return false;
            if (!goalWanted) { goalWanted = true; goalDeadline = Time.unscaledTime + 8f; }
            SendMilestones();
            return GoalAcknowledged;
        }
        public bool NotifyRevealStarted(bool revealStarted)
        {
            if (!revealStarted || !goalWanted || conversation == null
                || generation != conversation.ConversationGeneration || epoch != conversation.ControlEpoch) return false;
            if (!revealWanted) { revealWanted = true; revealDeadline = Time.unscaledTime + 8f; }
            SendMilestones();
            return RevealAcknowledged;
        }

        static string Ground(string surface)
        {
            switch (surface)
            {
                case "BookPlatform": case "BookPages": case "BookTopCover": return "book";
                case "RulerBridge": return "ruler";
                case "StartArea": return "desk";
                case "Plate": return "plate";
                default: return "unknown";
            }
        }
        static bool ValidAction(string action) => action == "STOP" || action == "FORWARD" || action == "TURN_R"
            || action == "TURN_L" || action == "FORWARD_R" || action == "FORWARD_L";
        [Serializable] sealed class FallEvidence
        {
            public string ground, lastAction, leftEdge, rightEdge;
            public bool technicalFault = false;
        }
    }
}
