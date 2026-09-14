using Flylingual.Conversation;
using Flylingual.PlayScreen;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Game-side steering assistance, not a neural readout or learned behaviour.</summary>
    [DisallowMultipleComponent]
    public sealed class FlyDemoSafetyAssist : MonoBehaviour
    {
        public bool enableDemoSafetyAssist = true;
        [Min(.1f)] public float nearGoalRadius = 3f;
        [Range(0, 1)] public float nearGoalMaxAssist = .45f;
        [Min(0)] public float noProgressStartTime = 8f;
        [Min(.001f)] public float progressThreshold = .1f;
        [Range(0, 1)] public float stuckMaxAssist = .35f;
        [Min(0)] public float emergencyStartTime = 45f;
        [Min(0)] public float hardEmergencyTime = 75f;
        [Range(0, 1)] public float maxTotalAssist = .65f;
        [Min(.01f)] public float assistChangeSpeed = .2f;
        public bool AssistanceEnabled => isActiveAndEnabled && enableDemoSafetyAssist;
        public float CurrentAssist { get; private set; }
        public float NoProgressSeconds { get; private set; }
        public float ElapsedSeconds { get; private set; }
        public float DistanceToGoal { get; private set; }
        public FlyMotorCommand RawMotor { get; private set; }
        public FlyMotorCommand AssistedMotor { get; private set; }

        BlindSugarRunSession stage;
        BlindSugarRunGoal goal;
        WindowsReplayDemo demo;
        ConversationSessionController conversation;
        FlyTerrainSensor sensor;
        float previousDistance = -1f;
        bool ForwardRequested => conversation != null && conversation.ActiveExecution != null
            && (conversation.ActiveExecution.action == "FORWARD" || conversation.ActiveExecution.action == "FORWARD_R"
                || conversation.ActiveExecution.action == "FORWARD_L");

        void Start()
        {
            stage = GetComponent<BlindSugarRunSession>();
            goal = GetComponent<BlindSugarRunGoal>();
            demo = FindAnyObjectByType<WindowsReplayDemo>();
            if (stage != null && demo != null && demo.body == stage.fly && demo.controller != null)
                demo.controller.SetDemoSafetyAssist(this);
        }

        bool Playing()
        {
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            return stage != null && stage.fly != null && stage.fly.Thorax != null && stage.State == BlindSugarRunSession.StageState.Playing
                && !TitleScreen.BlocksGameplay && Time.timeScale > 0 && conversation != null
                && conversation.BodyControlActive && conversation.HasFreshBrain && demo != null
                && demo.controller != null && demo.controller.MotorSource == demo.live;
        }

        void Update()
        {
            if (!AssistanceEnabled || TitleScreen.BlocksGameplay || stage == null
                || stage.State != BlindSugarRunSession.StageState.Playing)
            { ResetAssist(); return; }
            if (!Playing() || goal == null || goal.GoalVolume == null) return;
            Vector3 offset = goal.GoalVolume.bounds.center - stage.fly.Position;
            offset.y = 0;
            DistanceToGoal = offset.magnitude;
            ElapsedSeconds += Time.deltaTime;
            if (previousDistance < 0 || DistanceToGoal < previousDistance - Mathf.Max(.001f, progressThreshold))
            { previousDistance = DistanceToGoal; NoProgressSeconds = 0; }
            else if (ForwardRequested && RawMotor.forward > .01f) NoProgressSeconds += Time.deltaTime;
            // STOP/turning freezes this clock; repeated short forward requests
            // can still accumulate a real stall without overriding a STOP.
        }

        public FlyMotorCommand ApplyAssist(FlyMotorCommand raw, FlyMotorSource source, float dt)
        {
            RawMotor = AssistedMotor = raw;
            if (!AssistanceEnabled || !Playing() || !ForwardRequested || source != demo.live || !demo.live.HasFreshFrame
                || goal == null || goal.GoalVolume == null || !goal.GoalVolume.enabled
                || !goal.GoalVolume.gameObject.activeInHierarchy || raw.forward <= .01f)
            { CurrentAssist = 0; return raw; }
            if (sensor == null) sensor = stage.fly.GetComponent<FlyTerrainSensor>();
            var observation = sensor == null ? null : sensor.Observation;
            if (sensor == null || !sensor.Fresh || observation == null || observation.queryOverflow
                || !observation.groundPresent || observation.bodyUnsafe)
            { CurrentAssist = 0; return raw; }

            Vector3 toGoal = goal.GoalVolume.bounds.center - stage.fly.Position;
            toGoal.y = 0;
            float distance = toGoal.magnitude;
            Vector3 heading = Vector3.ProjectOnPlane(stage.fly.Thorax.transform.forward, Vector3.up).normalized;
            float desiredTurn = Mathf.Clamp(Vector3.SignedAngle(heading, toGoal, Vector3.up) / 90f, -1f, 1f);
            // Existing local edge observations veto steering toward an unsafe side.
            if ((desiredTurn > .05f && observation.rightEdge != "safe")
                || (desiredTurn < -.05f && observation.leftEdge != "safe"))
            { CurrentAssist = 0; return raw; }
            float ratio = distance / Mathf.Max(.1f, nearGoalRadius);
            float near = ratio < 1f / 3f ? nearGoalMaxAssist
                : ratio < 2f / 3f ? nearGoalMaxAssist * (25f / 45f)
                : ratio < 1f ? nearGoalMaxAssist * (10f / 45f) : 0;
            float stuck = NoProgressSeconds >= noProgressStartTime + 17f ? stuckMaxAssist
                : NoProgressSeconds >= noProgressStartTime + 7f ? stuckMaxAssist * (20f / 35f)
                : NoProgressSeconds >= noProgressStartTime ? stuckMaxAssist * (10f / 35f) : 0;
            float emergency = ElapsedSeconds >= Mathf.Max(emergencyStartTime, hardEmergencyTime) ? .45f
                : ElapsedSeconds >= emergencyStartTime ? .2f : 0;
            float target = Mathf.Clamp(near + stuck + emergency, 0, Mathf.Clamp01(maxTotalAssist));
            CurrentAssist = Mathf.MoveTowards(CurrentAssist, target, Mathf.Max(.01f, assistChangeSpeed) * Mathf.Max(0, dt));
            // Keep the brain's forward speed and scale steering by its existing activity.
            float activity = Mathf.Max(raw.forward, Mathf.Abs(raw.turn));
            AssistedMotor = new FlyMotorCommand(raw.forward, Mathf.Lerp(raw.turn, desiredTurn * activity, CurrentAssist));
            return AssistedMotor;
        }

        void ResetAssist()
        {
            CurrentAssist = NoProgressSeconds = ElapsedSeconds = 0;
            previousDistance = -1;
            RawMotor = AssistedMotor = FlyMotorCommand.Stop;
        }
        void OnDisable() => ResetAssist();
    }
}
