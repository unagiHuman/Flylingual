using System;
using UnityEngine;

namespace FlyLocomotionPoC
{
    [Serializable] public sealed class FlyTerrainFootState
    {
        public string leg, state = "idle";
        public bool measuredSupport, landingValid;
        public Vector3 landing, correction, footPosition, nominalPosition, desiredPosition;
        public float surfaceHeight, landingError;
        [NonSerialized] public bool wasSwing, initialized;
        [NonSerialized] public float wait, clearanceWait;
        [NonSerialized] public Vector3 lastAngles;
    }
    [DisallowMultipleComponent]
    public sealed class FlyTerrainTraversal : MonoBehaviour
    {
        [SerializeField, Range(5f, 50f)] float maximumCorrectionDegrees = 35f;
        [SerializeField, Range(10f, 180f)] float correctionSpeedDegrees = 90f;
        [SerializeField, Range(.02f, .2f)] float swingClearanceFraction = .07f;
        [SerializeField, Range(.02f, .3f)] float contactWaitSeconds = .12f;
        [SerializeField, Range(.05f, .5f)] float stepClearanceWaitSeconds = .25f;
        [SerializeField, Range(0f, .2f)] float maximumPostureLiftFraction = .12f;
        FlyBody body;
        FlyTerrainSensor sensor;
        FlyLocomotionController controller;
        readonly FlyTerrainKinematics kinematics = new FlyTerrainKinematics();
        public FlyTerrainFootState[] Feet { get; private set; }
        public bool SafetyHold { get; private set; }
        public bool WaitingForContact { get; private set; }
        public bool WaitingForClearance { get; private set; }
        public string Reason { get; private set; } = "idle";
        public bool Active { get; private set; }
        public float PostureLift { get; private set; }
        float standingClearance = -1f;
        public void Configure(FlyBody owner, FlyTerrainSensor sensing, FlyLocomotionController driver)
        {
            body = owner; sensor = sensing; controller = driver;
            Feet = new FlyTerrainFootState[body.Legs.Count];
            for (int i = 0; i < Feet.Length; i++) Feet[i] = new FlyTerrainFootState { leg = body.Legs[i].LegId };
        }
        public bool BeginStep(FlyMotorCommand raw, FlyMotorCommand motor, float phase, FlyLocomotionConfig config, float dt)
        {
            // Replay/mock and disconnected/STOP sources never enable a terrain gait.
            var live = controller.MotorSource as BrainMotorSource;
            Active = enabled && live != null && live.HasFreshFrame && config.groundedTripodGait
                && Mathf.Max(Mathf.Abs(raw.forward), Mathf.Abs(raw.turn)) >= config.gaitStartThreshold;
            SafetyHold = WaitingForContact = WaitingForClearance = false; Reason = Active ? "walking" : "idle";
            for (int i = 0; i < Feet.Length; i++)
            {
                var leg = body.Legs[i]; var f = Feet[i];
                f.footPosition = leg.FootProbePosition;
                f.measuredSupport = leg.FootContact.HasFreshSurfaceContact && Vector3.Dot(leg.FootContact.SurfaceNormal, sensor.Up) >= .65f;
            }
            if (!Active) { PostureLift = 0f; foreach (var f in Feet) { f.state = "idle"; f.landingValid = false; f.correction = Vector3.zero; f.wasSwing = false; f.initialized = false; f.wait = f.clearanceWait = 0; } return false; }
            var o = sensor.Observation;
            if (standingClearance < 0f && sensor.Fresh && o.groundPresent) standingClearance = o.bodyHeight;
            float lowest = float.PositiveInfinity, highest = float.NegativeInfinity;
            for (int i = 0; i < Feet.Length; i++) if (Feet[i].measuredSupport)
            {
                float height = Vector3.Dot(body.Legs[i].FootContact.SurfaceContactPoint, sensor.Up);
                lowest = Mathf.Min(lowest, height); highest = Mathf.Max(highest, height);
            }
            float wantedLift = highest - lowest > sensor.Reach * .025f
                ? Mathf.Clamp(highest + standingClearance - Vector3.Dot(body.Position, sensor.Up), 0f, sensor.Reach * maximumPostureLiftFraction) : 0f;
            PostureLift = Mathf.MoveTowards(PostureLift, wantedLift, sensor.Reach * .5f * dt);
            if (!sensor.Fresh || o.queryOverflow || !o.groundPresent || o.bodyUnsafe)
            { SafetyHold = true; Reason = !sensor.Fresh ? "stale_sensor" : o.bodyUnsafe ? "body_unsafe" : "ground_unknown"; }
            else if (raw.forward > config.gaitStartThreshold && (o.forwardBlocked || o.leftEdge == "very_near" || o.rightEdge == "very_near"))
            { SafetyHold = true; Reason = o.forwardBlocked ? "obstacle_too_high" : "edge"; }
            for (int i = 0; i < Feet.Length; i++)
            {
                var leg = body.Legs[i]; var f = Feet[i];
                var target = leg.CalculateNominalTargets(phase, motor, config);
                if (!target.stance && f.landingValid && !SafetyHold
                    && Vector3.Dot(f.landing - o.ground.point, sensor.Up) > sensor.Reach * .025f
                    && Vector3.Dot(leg.FootProbePosition - f.landing, sensor.Up) < sensor.FootRadius(leg))
                {
                    // Lift before advancing into a riser. Angular correction is
                    // rate-limited, so a fixed swing can otherwise end too soon.
                    f.clearanceWait += dt;
                    if (f.clearanceWait < stepClearanceWaitSeconds)
                    { WaitingForClearance = true; Reason = "awaiting_step_clearance"; }
                }
                else if (target.stance) f.clearanceWait = 0f;
                if (f.wasSwing && target.stance && !f.measuredSupport && !SafetyHold)
                {
                    f.wait += dt;
                    if (f.wait < contactWaitSeconds) { WaitingForContact = true; Reason = "awaiting_foot_contact"; }
                }
                else f.wait = 0;
            }
            return SafetyHold || WaitingForContact || WaitingForClearance;
        }
        public FlyLeg.LegDriveTarget Adjust(FlyLeg leg, FlyLeg.LegDriveTarget target, float phase, FlyMotorCommand motor, FlyLocomotionConfig config, float dt)
        {
            if (!Active) return target;
            int index = -1;
            for (int i = 0; i < body.Legs.Count; i++) if (body.Legs[i] == leg) { index = i; break; }
            if (index < 0) return target;
            var f = Feet[index];
            if (SafetyHold)
            {
                target.angles = f.initialized ? f.lastAngles : CurrentAngles(leg);
                target.stance = f.measuredSupport; f.state = Reason;
                return target;
            }
            float radius = sensor.FootRadius(leg);
            Vector3 up = sensor.Up;
            float baseHeight = Vector3.Dot(sensor.Observation.ground.point, up);
            Vector3 nominalPoint = kinematics.Endpoint(leg, target.angles);
            float legPhase = Mathf.Repeat(phase + (leg.Group == FlyLeg.TripodGroup.A ? 0f : Mathf.PI), Mathf.PI * 2f);
            bool swing = !target.stance;
            if (swing)
            {
                if (!f.wasSwing) f.landingValid = false;
                float landingPhase = leg.Group == FlyLeg.TripodGroup.A ? Mathf.PI : 0f;
                var landingTarget = leg.CalculateNominalTargets(landingPhase, motor, config);
                Vector3 predicted = kinematics.Endpoint(leg, landingTarget.angles);
                float remaining = (Mathf.PI - legPhase) / (2f * Mathf.PI * Mathf.Max(.1f, config.gaitFrequencyHz));
                predicted += Vector3.ClampMagnitude(Vector3.ProjectOnPlane(body.LinearVelocity, up) * Mathf.Max(0f, remaining), sensor.Reach * .3f);
                // Keep the highest verified surface for this swing. A sample
                // straddling a step edge must not lower an already lifting foot.
                if (f.landingValid)
                {
                    var previous = sensor.GroundAt(f.landing, baseHeight, radius);
                    f.landingValid = previous.walkable && previous.wideEnough
                        && Mathf.Abs(Vector3.Dot(previous.point - f.landing, up)) < radius;
                }
                ConsiderLanding(f, predicted, baseHeight, radius);
                ConsiderLanding(f, nominalPoint, baseHeight, radius);
                if (motor.forward > config.gaitStartThreshold)
                    ConsiderLanding(f, predicted + sensor.Forward * sensor.Reach * .25f, baseHeight, radius);
            }
            if (!swing && f.measuredSupport)
            {
                f.landing = leg.FootContact.SurfaceContactPoint;
                f.landingValid = true;
            }
            if (!f.initialized && !swing)
            {
                var ground = sensor.GroundAt(leg.FootProbePosition, baseHeight, radius);
                if (ground.walkable && ground.wideEnough) { f.landing = ground.point; f.landingValid = true; }
            }
            if (!f.landingValid)
            {
                // Leave the last supported configuration in place. No fabricated contact.
                target.angles = f.initialized ? f.lastAngles : CurrentAngles(leg);
                target.stance = f.measuredSupport;
                f.state = "no_landing";
                return target;
            }
            float surfaceHeight = Vector3.Dot(f.landing, up);
            f.surfaceHeight = surfaceHeight;
            Vector3 goal = nominalPoint;
            float wantedHeight = surfaceHeight + radius;
            // A virtual support-pose offset extends planted legs while their
            // real contacts lift the body. No root transform or force is written.
            if (!swing && f.measuredSupport) wantedHeight -= PostureLift;
            if (swing)
            {
                float wave = Mathf.Sin(legPhase);
                // Clearance is geometric, not proportional to the Brain's forward amplitude.
                wantedHeight = Mathf.Max(wantedHeight, baseHeight + radius) + Mathf.Max(0f, wave) * sensor.Reach * swingClearanceFraction;
            }
            float delta = wantedHeight - Vector3.Dot(nominalPoint, up);
            // Preserve the calibrated flat stance exactly within contact tolerance.
            if (!swing && Mathf.Abs(delta) < radius * .15f) delta = 0f;
            goal += up * Mathf.Clamp(delta, -sensor.MaximumDrop, sensor.MaximumStep + sensor.Reach * swingClearanceFraction);
            var corrected = kinematics.Solve(leg, target.angles, goal, maximumCorrectionDegrees);
            Vector3 wantedOffset = corrected - target.angles;
            f.correction = Vector3.MoveTowards(f.correction, wantedOffset, correctionSpeedDegrees * dt);
            target.angles += f.correction;
            for (int j = 0; j < 3; j++)
            {
                var drive = (j == 0 ? leg.Coxa : j == 1 ? leg.Femur : leg.Tibia).Articulation.xDrive;
                target.angles[j] = Mathf.Clamp(target.angles[j], drive.lowerLimit, drive.upperLimit);
            }
            f.nominalPosition = nominalPoint; f.desiredPosition = goal;
            f.landingError = Vector3.Distance(kinematics.Endpoint(leg, target.angles), goal);
            f.state = swing ? "swing_clearance" : f.measuredSupport ? "supported" : "seeking_contact";
            f.wasSwing = swing || (!f.measuredSupport && f.wait < contactWaitSeconds && f.wasSwing);
            f.lastAngles = target.angles; f.initialized = true;
            return target;
        }
        void ConsiderLanding(FlyTerrainFootState foot, Vector3 position, float floor, float radius)
        {
            var ground = sensor.GroundAt(position, floor, radius);
            float rise = ground.found ? Vector3.Dot(ground.point, sensor.Up) - floor : float.PositiveInfinity;
            if (!ground.walkable || !ground.wideEnough || rise > sensor.MaximumStep || rise < -sensor.MaximumDrop) return;
            if (!foot.landingValid || Vector3.Dot(ground.point - foot.landing, sensor.Up) > 0f)
            { foot.landing = ground.point; foot.landingValid = true; }
        }
        static Vector3 CurrentAngles(FlyLeg leg) => new Vector3(leg.Coxa.Articulation.jointPosition[0],
            leg.Femur.Articulation.jointPosition[0], leg.Tibia.Articulation.jointPosition[0]) * Mathf.Rad2Deg;
    }
}
