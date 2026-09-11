using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace FlyLocomotionPoC
{
    [Serializable]
    public sealed class FlyStepRearLegKinematicsSummary
    {
        public string legId;
        public int sampleCount;
        public int swingCount;
        public float meanSwingDurationSeconds;
        public float maxFootHeight;
        public float maxRelativeFootHeight;
        public float maxForwardReachFromFrontMeters;
        public float maxForwardReachFromTopStartMeters;
        public float minDistanceToTopEdgeMeters;
        public float maxSwingFootHeight;
        public float maxSwingForwardReachFromFrontMeters;
        public float minSwingDistanceToTopEdgeMeters;
        public float firstSwingStartPhaseDegrees = -1f;
        public float lastSwingEndPhaseDegrees = -1f;
        public FlyMetricStatistic footWorldX = new FlyMetricStatistic();
        public FlyMetricStatistic footWorldY = new FlyMetricStatistic();
        public FlyMetricStatistic footRelativeX = new FlyMetricStatistic();
        public FlyMetricStatistic footRelativeY = new FlyMetricStatistic();
        public FlyMetricStatistic coxaTargetDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic femurTargetDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic tibiaTargetDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic coxaActualDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic femurActualDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic tibiaActualDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic coxaTrackingErrorDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic femurTrackingErrorDegrees = new FlyMetricStatistic();
        public FlyMetricStatistic tibiaTrackingErrorDegrees = new FlyMetricStatistic();
        public int frontContactEvents;
        public int topContactEvents;
        public float frontContactSeconds;
        public float topContactSeconds;
    }

    [Serializable]
    public sealed class FlyStepKinematicsTrialResult
    {
        public int protocolVersion = 1;
        public int trialId;
        public string source;
        public float commandForward;
        public float obstacleHeight;
        public float obstacleFrontX;
        public float obstacleTopStartX;
        public float durationSeconds;
        public string diagnosticConclusion = "UNKNOWN";
        public string diagnosticBasis = string.Empty;
        public List<FlyStepRearLegKinematicsSummary> rearLegs = new List<FlyStepRearLegKinematicsSummary>();
    }

    /// <summary>
    /// Bounded kinematics capture for the two hind legs.  It is enabled only
    /// for step characterization and never changes physics or joint targets.
    /// </summary>
    public sealed class FlyStepKinematicsDiagnostics : MonoBehaviour
    {
        private sealed class Accumulator
        {
            public readonly FlyLeg leg;
            public int sampleCount;
            public int swingCount;
            public float swingDurationSum;
            public bool wasSwing;
            public float swingStartedAt;
            public float firstSwingStartPhase = -1f;
            public float lastSwingEndPhase = -1f;
            public int previousFrontEvents;
            public int previousTopEvents;
            public readonly List<float> footWorldX = new List<float>();
            public readonly List<float> footWorldY = new List<float>();
            public readonly List<float> footRelativeX = new List<float>();
            public readonly List<float> footRelativeY = new List<float>();
            public readonly List<float> coxaTarget = new List<float>();
            public readonly List<float> femurTarget = new List<float>();
            public readonly List<float> tibiaTarget = new List<float>();
            public readonly List<float> coxaActual = new List<float>();
            public readonly List<float> femurActual = new List<float>();
            public readonly List<float> tibiaActual = new List<float>();
            public readonly List<float> coxaError = new List<float>();
            public readonly List<float> femurError = new List<float>();
            public readonly List<float> tibiaError = new List<float>();
            public float maxFootHeight = float.MinValue;
            public float maxRelativeFootHeight = float.MinValue;
            public float maxForwardReachFromFront = float.MinValue;
            public float maxForwardReachFromTopStart = float.MinValue;
            public float minDistanceToTopEdge = float.MaxValue;
            public int frontContactEvents;
            public int topContactEvents;
            public float frontContactSeconds;
            public float topContactSeconds;
            public float maxSwingFootHeight = float.MinValue;
            public float maxSwingForwardReachFromFront = float.MinValue;
            public float minSwingDistanceToTopEdge = float.MaxValue;
            public Vector3 previousFootPosition;
            public bool hasPreviousFootPosition;

            public Accumulator(FlyLeg sourceLeg)
            {
                leg = sourceLeg;
            }
        }

        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyLocomotionController controller;
        [SerializeField] private FlyStepObstacle obstacle;
        [SerializeField] private float traceIntervalSeconds = 0.02f;

        private readonly List<Accumulator> accumulators = new List<Accumulator>();
        private StreamWriter traceWriter;
        private bool active;
        private float trialStartedAt;
        private int trialId;
        private string source = string.Empty;
        private float commandForward;

        public void Configure(FlyBody body, FlyLocomotionController locomotionController, FlyStepObstacle step)
        {
            flyBody = body;
            controller = locomotionController;
            obstacle = step;
        }

        public void BeginTrial(int id, string trialSource, float forward)
        {
            EndTrial();
            trialId = id;
            source = trialSource ?? string.Empty;
            commandForward = forward;
            trialStartedAt = Time.unscaledTime;
            accumulators.Clear();
            if (flyBody != null)
            {
                IReadOnlyList<FlyLeg> legs = flyBody.Legs;
                for (int i = 0; i < legs.Count; i++)
                {
                    FlyLeg leg = legs[i];
                    if (leg != null && leg.LegId.EndsWith("H", StringComparison.Ordinal))
                    {
                        accumulators.Add(new Accumulator(leg));
                    }
                }
            }

            string tracePath = GetCommandLineValue("-flyStepKinematicsTrace");
            if (!string.IsNullOrEmpty(tracePath))
            {
                string directory = Path.GetDirectoryName(tracePath);
                if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                traceWriter = new StreamWriter(tracePath, false);
                traceWriter.WriteLine("trial,elapsed,leg,global_phase,rear_leg_phase,stance_progress,swing,foot_x,foot_y,foot_z,foot_velocity_x,foot_velocity_y,foot_velocity_z,foot_rel_x,foot_rel_y,coxa_base_target,coxa_target,femur_base_target,femur_target,tibia_base_target,tibia_target,coxa_actual,femur_actual,tibia_actual,coxa_velocity,femur_velocity,tibia_velocity,front_events,top_events,top_contact,front_contact,contact_x,contact_y,contact_z,normal_x,normal_y,normal_z,relative_velocity_x,relative_velocity_y,relative_velocity_z,relative_normal_velocity,tangential_speed,impulse,normal_impulse,contact_front_edge_distance,contact_back_edge_distance,contact_left_edge_distance,contact_right_edge_distance,foot_front_edge_distance,foot_back_edge_distance,foot_left_edge_distance,foot_right_edge_distance,grounded,support_count,thorax_x,thorax_y,thorax_z,thorax_velocity_x,thorax_velocity_y,thorax_velocity_z,thorax_angular_velocity_x,thorax_angular_velocity_y,thorax_angular_velocity_z,pitch,roll,raw_forward,effective_forward,reflex_state,reflex_active_leg,rear_step_up_active,rear_propulsion_active,rear_stance_coxa_multiplier,reflex_blend,reflex_coxa_offset,reflex_femur_offset,reflex_tibia_offset");
            }

            active = true;
        }

        public void EndTrial()
        {
            if (!active)
            {
                CloseTrace();
                return;
            }

            active = false;
            CloseTrace();
            WriteSummary();
        }

        private void FixedUpdate()
        {
            if (!active || controller == null || flyBody == null || obstacle == null)
            {
                return;
            }

            float elapsed = Time.unscaledTime - trialStartedAt;
            for (int i = 0; i < accumulators.Count; i++)
            {
                Record(accumulators[i], elapsed);
            }
        }

        private void Record(Accumulator accumulator, float elapsed)
        {
            FlyLeg leg = accumulator.leg;
            Vector3 foot = leg.FootProbePosition;
            Vector3 footVelocity = accumulator.hasPreviousFootPosition
                ? (foot - accumulator.previousFootPosition) / Mathf.Max(0.0001f, Time.fixedDeltaTime)
                : Vector3.zero;
            accumulator.previousFootPosition = foot;
            accumulator.hasPreviousFootPosition = true;
            Vector3 relative = foot - flyBody.Position;
            float distanceToTopEdge = Vector2.Distance(
                new Vector2(foot.x, foot.y),
                new Vector2(obstacle.UpperPlatformStartX, obstacle.ObstacleHeight));
            bool swing = IsSwing(leg, controller.Phase);
            if (swing && !accumulator.wasSwing)
            {
                accumulator.swingCount++;
                accumulator.swingStartedAt = elapsed;
                if (accumulator.firstSwingStartPhase < 0f)
                {
                    accumulator.firstSwingStartPhase = PhaseDegrees(leg, controller.Phase);
                }
            }
            else if (!swing && accumulator.wasSwing)
            {
                accumulator.swingDurationSum += Mathf.Max(0f, elapsed - accumulator.swingStartedAt);
                accumulator.lastSwingEndPhase = PhaseDegrees(leg, controller.Phase);
            }

            accumulator.wasSwing = swing;
            accumulator.sampleCount++;
            accumulator.footWorldX.Add(foot.x);
            accumulator.footWorldY.Add(foot.y);
            accumulator.footRelativeX.Add(relative.x);
            accumulator.footRelativeY.Add(relative.y);
            float coxaActual = ActualAngle(leg.Coxa);
            float femurActual = ActualAngle(leg.Femur);
            float tibiaActual = ActualAngle(leg.Tibia);
            accumulator.coxaTarget.Add(leg.Coxa == null ? 0f : leg.Coxa.Target);
            accumulator.femurTarget.Add(leg.Femur == null ? 0f : leg.Femur.Target);
            accumulator.tibiaTarget.Add(leg.Tibia == null ? 0f : leg.Tibia.Target);
            accumulator.coxaActual.Add(coxaActual);
            accumulator.femurActual.Add(femurActual);
            accumulator.tibiaActual.Add(tibiaActual);
            accumulator.coxaError.Add(Mathf.Abs((leg.Coxa == null ? 0f : leg.Coxa.Target) - coxaActual));
            accumulator.femurError.Add(Mathf.Abs((leg.Femur == null ? 0f : leg.Femur.Target) - femurActual));
            accumulator.tibiaError.Add(Mathf.Abs((leg.Tibia == null ? 0f : leg.Tibia.Target) - tibiaActual));
            accumulator.maxFootHeight = Mathf.Max(accumulator.maxFootHeight, foot.y);
            accumulator.maxRelativeFootHeight = Mathf.Max(accumulator.maxRelativeFootHeight, relative.y);
            accumulator.maxForwardReachFromFront = Mathf.Max(accumulator.maxForwardReachFromFront, foot.x - obstacle.FrontX);
            accumulator.maxForwardReachFromTopStart = Mathf.Max(accumulator.maxForwardReachFromTopStart, foot.x - obstacle.UpperPlatformStartX);
            accumulator.minDistanceToTopEdge = Mathf.Min(accumulator.minDistanceToTopEdge, distanceToTopEdge);

            if (swing)
            {
                accumulator.maxSwingFootHeight = Mathf.Max(accumulator.maxSwingFootHeight, foot.y);
                accumulator.maxSwingForwardReachFromFront = Mathf.Max(accumulator.maxSwingForwardReachFromFront, foot.x - obstacle.FrontX);
                accumulator.minSwingDistanceToTopEdge = Mathf.Min(accumulator.minSwingDistanceToTopEdge, distanceToTopEdge);
            }

            int frontEvents = obstacle.GetFrontLegEventsForLeg(leg.LegId);
            int topEvents = obstacle.GetTopLegEventsForLeg(leg.LegId);
            if (frontEvents > accumulator.previousFrontEvents)
            {
                accumulator.frontContactEvents += frontEvents - accumulator.previousFrontEvents;
            }
            if (topEvents > accumulator.previousTopEvents)
            {
                accumulator.topContactEvents += topEvents - accumulator.previousTopEvents;
            }
            accumulator.previousFrontEvents = frontEvents;
            accumulator.previousTopEvents = topEvents;
            accumulator.frontContactSeconds = obstacle.GetFrontLegSecondsForLeg(leg.LegId);
            accumulator.topContactSeconds = obstacle.GetTopLegSecondsForLeg(leg.LegId);

            if (traceWriter != null && elapsed >= 0f)
            {
                FlyStepObstacle.LegContactSnapshot contact = default;
                bool hasContact = obstacle.TryGetLegContactSnapshot(leg.LegId, out contact);
                Vector3 thoraxPosition = flyBody.Position;
                Vector3 thoraxVelocity = flyBody.LinearVelocity;
                Vector3 thoraxAngularVelocity = flyBody.AngularVelocity;
                Vector3 thoraxAngles = flyBody.Thorax == null ? flyBody.transform.eulerAngles : flyBody.Thorax.transform.eulerAngles;
                FlyLocalReflexLayer reflex = controller.ReflexLayer;
                float rearLegPhase = RearLegPhase(leg, controller.Phase);
                float stanceProgress = StanceProgress(rearLegPhase);
                float contactFrontDistance = contact.point.x - obstacle.TopSurfaceStartX;
                float contactBackDistance = obstacle.TopSurfaceEndX - contact.point.x;
                float contactLeftDistance = contact.point.z + obstacle.UpperPlatformHalfWidth;
                float contactRightDistance = obstacle.UpperPlatformHalfWidth - contact.point.z;
                traceWriter.WriteLine(string.Join(",", new[]
                {
                    trialId.ToString(CultureInfo.InvariantCulture),
                    elapsed.ToString("0.000", CultureInfo.InvariantCulture),
                    leg.LegId,
                    controller.Phase.ToString("0.000000", CultureInfo.InvariantCulture),
                    rearLegPhase.ToString("0.000000", CultureInfo.InvariantCulture),
                    stanceProgress.ToString("0.000000", CultureInfo.InvariantCulture),
                    swing ? "1" : "0",
                    foot.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    foot.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    foot.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    footVelocity.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    footVelocity.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    footVelocity.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    relative.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    relative.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    leg.LastBaseCoxaTarget.ToString("0.000", CultureInfo.InvariantCulture),
                    (leg.Coxa == null ? 0f : leg.Coxa.Target).ToString("0.000", CultureInfo.InvariantCulture),
                    leg.LastBaseFemurTarget.ToString("0.000", CultureInfo.InvariantCulture),
                    (leg.Femur == null ? 0f : leg.Femur.Target).ToString("0.000", CultureInfo.InvariantCulture),
                    leg.LastBaseTibiaTarget.ToString("0.000", CultureInfo.InvariantCulture),
                    (leg.Tibia == null ? 0f : leg.Tibia.Target).ToString("0.000", CultureInfo.InvariantCulture),
                    coxaActual.ToString("0.000", CultureInfo.InvariantCulture),
                    femurActual.ToString("0.000", CultureInfo.InvariantCulture),
                    tibiaActual.ToString("0.000", CultureInfo.InvariantCulture),
                    JointVelocity(leg.Coxa).ToString("0.000", CultureInfo.InvariantCulture),
                    JointVelocity(leg.Femur).ToString("0.000", CultureInfo.InvariantCulture),
                    JointVelocity(leg.Tibia).ToString("0.000", CultureInfo.InvariantCulture),
                    frontEvents.ToString(CultureInfo.InvariantCulture),
                    topEvents.ToString(CultureInfo.InvariantCulture),
                    hasContact && contact.top ? "1" : "0",
                    hasContact && contact.front ? "1" : "0",
                    contact.point.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.point.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.point.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.normal.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.normal.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.normal.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.relativeVelocity.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.relativeVelocity.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.relativeVelocity.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.relativeNormalVelocity.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.tangentialSpeed.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.impulseMagnitude.ToString("0.000000", CultureInfo.InvariantCulture),
                    contact.normalImpulseMagnitude.ToString("0.000000", CultureInfo.InvariantCulture),
                    contactFrontDistance.ToString("0.000000", CultureInfo.InvariantCulture),
                    contactBackDistance.ToString("0.000000", CultureInfo.InvariantCulture),
                    contactLeftDistance.ToString("0.000000", CultureInfo.InvariantCulture),
                    contactRightDistance.ToString("0.000000", CultureInfo.InvariantCulture),
                    (foot.x - obstacle.TopSurfaceStartX).ToString("0.000000", CultureInfo.InvariantCulture),
                    (obstacle.TopSurfaceEndX - foot.x).ToString("0.000000", CultureInfo.InvariantCulture),
                    (foot.z + obstacle.UpperPlatformHalfWidth).ToString("0.000000", CultureInfo.InvariantCulture),
                    (obstacle.UpperPlatformHalfWidth - foot.z).ToString("0.000000", CultureInfo.InvariantCulture),
                    leg.IsGrounded ? "1" : "0",
                    flyBody.GroundContactCount.ToString(CultureInfo.InvariantCulture),
                    thoraxPosition.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxPosition.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxPosition.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxVelocity.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxVelocity.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxVelocity.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxAngularVelocity.x.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxAngularVelocity.y.ToString("0.000000", CultureInfo.InvariantCulture),
                    thoraxAngularVelocity.z.ToString("0.000000", CultureInfo.InvariantCulture),
                    NormalizeAngle(thoraxAngles.z).ToString("0.000", CultureInfo.InvariantCulture),
                    NormalizeAngle(thoraxAngles.x).ToString("0.000", CultureInfo.InvariantCulture),
                    (reflex == null ? controller.CurrentMotor.forward : reflex.RawForward).ToString("0.000", CultureInfo.InvariantCulture),
                    (reflex == null ? controller.CurrentMotor.forward : reflex.EffectiveForward).ToString("0.000", CultureInfo.InvariantCulture),
                    reflex == null ? "NONE" : reflex.RearStepUpStateName,
                    reflex == null ? string.Empty : reflex.ActiveRearLegId,
                    reflex != null && reflex.RearStepUpActive ? "1" : "0",
                    reflex != null && reflex.RearPropulsionActive ? "1" : "0",
                    (reflex == null ? 1f : reflex.RearStanceCoxaMultiplier).ToString("0.000", CultureInfo.InvariantCulture),
                    (reflex == null ? 0f : reflex.RearStepUpBlend).ToString("0.000", CultureInfo.InvariantCulture),
                    (reflex == null ? 0f : reflex.RearStepUpCoxaOffsetAppliedDegrees).ToString("0.000", CultureInfo.InvariantCulture),
                    (reflex == null ? 0f : reflex.RearStepUpFemurOffsetAppliedDegrees).ToString("0.000", CultureInfo.InvariantCulture),
                    (reflex == null ? 0f : reflex.RearStepUpTibiaOffsetAppliedDegrees).ToString("0.000", CultureInfo.InvariantCulture)
                }));
            }
        }

        private void WriteSummary()
        {
            string outputPath = GetCommandLineValue("-flyStepKinematicsOutput");
            if (string.IsNullOrEmpty(outputPath))
            {
                return;
            }

            FlyStepKinematicsTrialResult result = new FlyStepKinematicsTrialResult
            {
                trialId = trialId,
                source = source,
                commandForward = commandForward,
                obstacleHeight = obstacle == null ? 0f : obstacle.ObstacleHeight,
                obstacleFrontX = obstacle == null ? 0f : obstacle.FrontX,
                obstacleTopStartX = obstacle == null ? 0f : obstacle.UpperPlatformStartX,
                durationSeconds = Time.unscaledTime - trialStartedAt,
                diagnosticConclusion = "UNKNOWN",
                diagnosticBasis = "Summary statistics only; compare forward=0.74 against forward=0.90/1.00."
            };

            for (int i = 0; i < accumulators.Count; i++)
            {
                result.rearLegs.Add(BuildSummary(accumulators[i]));
            }

            string directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            File.WriteAllText(outputPath, JsonUtility.ToJson(result, true) + Environment.NewLine);
        }

        private static FlyStepRearLegKinematicsSummary BuildSummary(Accumulator accumulator)
        {
            if (accumulator.wasSwing)
            {
                accumulator.swingDurationSum += Mathf.Max(0f, Time.fixedDeltaTime);
            }

            return new FlyStepRearLegKinematicsSummary
            {
                legId = accumulator.leg.LegId,
                sampleCount = accumulator.sampleCount,
                swingCount = accumulator.swingCount,
                meanSwingDurationSeconds = accumulator.swingCount == 0 ? 0f : accumulator.swingDurationSum / accumulator.swingCount,
                maxFootHeight = SafeMax(accumulator.maxFootHeight),
                maxRelativeFootHeight = SafeMax(accumulator.maxRelativeFootHeight),
                maxForwardReachFromFrontMeters = SafeMax(accumulator.maxForwardReachFromFront),
                maxForwardReachFromTopStartMeters = SafeMax(accumulator.maxForwardReachFromTopStart),
                minDistanceToTopEdgeMeters = SafeMin(accumulator.minDistanceToTopEdge),
                maxSwingFootHeight = SafeMax(accumulator.maxSwingFootHeight),
                maxSwingForwardReachFromFrontMeters = SafeMax(accumulator.maxSwingForwardReachFromFront),
                minSwingDistanceToTopEdgeMeters = SafeMin(accumulator.minSwingDistanceToTopEdge),
                firstSwingStartPhaseDegrees = accumulator.firstSwingStartPhase,
                lastSwingEndPhaseDegrees = accumulator.lastSwingEndPhase,
                footWorldX = BuildStatistic(accumulator.footWorldX),
                footWorldY = BuildStatistic(accumulator.footWorldY),
                footRelativeX = BuildStatistic(accumulator.footRelativeX),
                footRelativeY = BuildStatistic(accumulator.footRelativeY),
                coxaTargetDegrees = BuildStatistic(accumulator.coxaTarget),
                femurTargetDegrees = BuildStatistic(accumulator.femurTarget),
                tibiaTargetDegrees = BuildStatistic(accumulator.tibiaTarget),
                coxaActualDegrees = BuildStatistic(accumulator.coxaActual),
                femurActualDegrees = BuildStatistic(accumulator.femurActual),
                tibiaActualDegrees = BuildStatistic(accumulator.tibiaActual),
                coxaTrackingErrorDegrees = BuildStatistic(accumulator.coxaError),
                femurTrackingErrorDegrees = BuildStatistic(accumulator.femurError),
                tibiaTrackingErrorDegrees = BuildStatistic(accumulator.tibiaError),
                frontContactEvents = accumulator.frontContactEvents,
                topContactEvents = accumulator.topContactEvents,
                frontContactSeconds = accumulator.frontContactSeconds,
                topContactSeconds = accumulator.topContactSeconds
            };
        }

        private static FlyMetricStatistic BuildStatistic(List<float> values)
        {
            if (values.Count == 0) return new FlyMetricStatistic();
            float min = values[0];
            float max = values[0];
            double sum = 0.0;
            for (int i = 0; i < values.Count; i++)
            {
                min = Mathf.Min(min, values[i]);
                max = Mathf.Max(max, values[i]);
                sum += values[i];
            }

            return new FlyMetricStatistic { mean = (float)(sum / values.Count), min = min, max = max };
        }

        private static float ActualAngle(FlyJoint joint)
        {
            if (joint == null || joint.Articulation == null || joint.Articulation.jointPosition.dofCount == 0)
            {
                return 0f;
            }

            return joint.Articulation.jointPosition[0] * Mathf.Rad2Deg;
        }

        private static float JointVelocity(FlyJoint joint)
        {
            if (joint == null || joint.Articulation == null || joint.Articulation.jointVelocity.dofCount == 0)
            {
                return 0f;
            }

            return joint.Articulation.jointVelocity[0] * Mathf.Rad2Deg;
        }

        private static float NormalizeAngle(float degrees)
        {
            return Mathf.DeltaAngle(0f, degrees);
        }

        private static bool IsSwing(FlyLeg leg, float phase)
        {
            float legPhase = leg.Group == FlyLeg.TripodGroup.A ? phase : phase + Mathf.PI;
            return Mathf.Sin(legPhase) > 0f;
        }

        private static float PhaseDegrees(FlyLeg leg, float phase)
        {
            float legPhase = leg.Group == FlyLeg.TripodGroup.A ? phase : phase + Mathf.PI;
            return Mathf.Repeat(legPhase * Mathf.Rad2Deg, 360f);
        }

        private static float RearLegPhase(FlyLeg leg, float phase)
        {
            return Mathf.Repeat(leg.Group == FlyLeg.TripodGroup.A ? phase : phase + Mathf.PI, 2f * Mathf.PI);
        }

        private static float StanceProgress(float rearLegPhase)
        {
            return rearLegPhase < Mathf.PI ? -1f : Mathf.Clamp01((rearLegPhase - Mathf.PI) / Mathf.PI);
        }

        private void CloseTrace()
        {
            if (traceWriter == null) return;
            traceWriter.Flush();
            traceWriter.Dispose();
            traceWriter = null;
        }

        private static float SafeMax(float value) => value == float.MinValue ? 0f : value;
        private static float SafeMin(float value) => value == float.MaxValue ? 0f : value;

        private static string GetCommandLineValue(string name)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name) return arguments[i + 1];
            }

            return string.Empty;
        }
    }
}
