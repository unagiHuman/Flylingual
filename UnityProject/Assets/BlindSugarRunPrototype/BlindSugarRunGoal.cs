using Flylingual.Conversation;
using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Game-owned completion, independent of narration and API responses.</summary>
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunGoal : MonoBehaviour
    {
        BlindSugarRunSession stage;
        ConversationSessionController conversation;
        FlyTerrainSensor sensor;
        BoxCollider goal;
        readonly BlindSugarRunGoalStability stability = new BlindSugarRunGoalStability();
        public bool InsideGoal { get; private set; }
        public float StableSeconds => (float)stability.StableSeconds;

        void Start()
        {
            stage = GetComponent<BlindSugarRunSession>();
            // Existing serialized kill-volume reference identifies this stage's exact Volumes container.
            Transform volumes = stage != null && stage.killVolume != null ? stage.killVolume.transform.parent : null;
            Transform target = null;
            int matches = 0;
            if (volumes != null && volumes.name == "Volumes")
                foreach (Transform child in volumes)
                    if (child.name == "GoalVolume") { target = child; matches++; }
            if (matches == 1 && target != null && target.gameObject.scene == gameObject.scene)
            {
                var candidates = target.GetComponents<BoxCollider>();
                if (candidates.Length == 1 && candidates[0].isTrigger) goal = candidates[0];
            }
            if (goal == null) { Debug.LogWarning("BLIND_SUGAR_GOAL_VOLUME_MISSING"); enabled = false; }
        }

        void Update()
        {
            if (stage == null || stage.fly == null || stage.State != BlindSugarRunSession.StageState.Playing)
            { ResetTiming(); return; }
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            if (sensor == null) sensor = stage.fly.GetComponent<FlyTerrainSensor>();
            var o = sensor == null ? null : sensor.Observation;
            InsideGoal = Contains(goal, stage.fly.Position);
            var body = conversation == null ? null : conversation.GetComponent<NativeConversationBody>();
            bool valid = InsideGoal && Time.timeScale > 0 && conversation != null && conversation.HasFreshBrain
                && conversation.BodyControlActive && body != null && body.BodyActive && string.IsNullOrEmpty(body.Fault)
                && sensor != null && sensor.Fresh && o != null && !o.queryOverflow && o.groundPresent && !o.bodyUnsafe
                && o.leftEdge == "safe" && o.rightEdge == "safe"
                && stage.fly.LinearVelocity.magnitude <= .03f && stage.fly.AngularVelocity.magnitude <= .08f;
            if (stability.Sample(Time.realtimeSinceStartupAsDouble, valid,
                conversation == null ? -1 : conversation.ControlEpoch,
                conversation == null ? -1 : conversation.ConversationGeneration)) stage.ConfirmGoal();
        }

        static bool Contains(BoxCollider volume, Vector3 position)
        {
            if (volume == null || !volume.enabled || !volume.gameObject.activeInHierarchy) return false;
            Vector3 p = volume.transform.InverseTransformPoint(position) - volume.center;
            Vector3 half = volume.size * .5f;
            return Mathf.Abs(p.x) <= half.x && Mathf.Abs(p.y) <= half.y && Mathf.Abs(p.z) <= half.z;
        }
        void ResetTiming() { stability.Reset(); }
    }
}
