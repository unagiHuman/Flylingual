using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyLeg : MonoBehaviour
    {
        public enum TripodGroup
        {
            A,
            B
        }

        [SerializeField] private string legId;
        [SerializeField] private bool leftSide;
        [SerializeField] private TripodGroup group;
        [SerializeField] private FlyJoint coxa;
        [SerializeField] private FlyJoint femur;
        [SerializeField] private FlyJoint tibia;
        [SerializeField] private FlyFootContact footContact;
        [SerializeField] private FlyFootAdhesion footAdhesion;

        public string LegId => legId;
        public bool LeftSide => leftSide;
        public TripodGroup Group => group;
        public FlyJoint Coxa => coxa;
        public FlyJoint Femur => femur;
        public FlyJoint Tibia => tibia;
        public FlyFootAdhesion FootAdhesion => footAdhesion;
        public FlyFootContact FootContact => footContact;
        public bool IsGrounded => footContact != null && footContact.TouchingGround;
        public Vector3 FootProbePosition => footContact == null ? Vector3.zero : footContact.ProbePosition;
        public float LastBaseCoxaTarget { get; private set; }
        public float LastCorrectedCoxaTarget { get; private set; }
        public float LastBaseFemurTarget { get; private set; }
        public float LastCorrectedFemurTarget { get; private set; }
        public float LastBaseTibiaTarget { get; private set; }
        public float LastCorrectedTibiaTarget { get; private set; }

        public void Configure(string id, bool isLeft, TripodGroup tripodGroup, FlyJoint coxaJoint, FlyJoint femurJoint, FlyJoint tibiaJoint, FlyFootContact contact, FlyFootAdhesion adhesion = null)
        {
            legId = id;
            leftSide = isLeft;
            group = tripodGroup;
            coxa = coxaJoint;
            femur = femurJoint;
            tibia = tibiaJoint;
            footContact = contact;
            footAdhesion = adhesion;
        }

        public struct LegDriveTarget
        {
            public Vector3 baseAngles, angles;
            public bool stance;
            public float stanceProgress;
        }

        // Pure calculation: does not write joints or adhesion state.
        public LegDriveTarget CalculateNominalTargets(float globalPhase, in FlyMotorCommand motor, FlyLocomotionConfig config,
                                    float coxaOffsetDegrees = 0f, float femurOffsetDegrees = 0f, float tibiaOffsetDegrees = 0f,
                                    float stanceCoxaMultiplier = 1f, float steeringTurn = float.NaN)
        {
            float legPhase = group == TripodGroup.A ? globalPhase : globalPhase + Mathf.PI;
            float strideWave = Mathf.Sin(legPhase);
            bool stance = strideWave <= 0f;
            float stanceProgress = stance ? Mathf.Clamp01(Mathf.Repeat(legPhase - Mathf.PI, 2f * Mathf.PI) / Mathf.PI) : 0f;
            float swingWave = Mathf.Max(0f, strideWave);
            float sideScale = config.SideScale(leftSide,float.IsNaN(steeringTurn) ? motor.turn : steeringTurn);
            float gaitDrive = Mathf.Max(Mathf.Abs(motor.forward), Mathf.Abs(motor.turn) * config.turnGaitContribution);
            // With the grounded rest pose, cosine moves the planted foot
            // continuously from front to back over the stance half-cycle.
            float stride = (config.groundedTripodGait ? Mathf.Cos(legPhase) : -strideWave)
                * config.coxaStrideAmplitudeDegrees * gaitDrive * sideScale;
            float baseCoxa = stride;
            if (stance) stride *= Mathf.Max(1f, stanceCoxaMultiplier);
            float lift = swingWave * gaitDrive;
            float femurBase = lift * config.femurLiftAmplitudeDegrees;
            float tibiaBase = -lift * config.tibiaLiftAmplitudeDegrees;
            if (config.groundedTripodGait)
            {
                // The two sides share bone-local hinge axes. Mirrored limbs
                // therefore need opposite drive signs for the same world lift.
                float sign = leftSide ? -1f : 1f;
                baseCoxa *= sign;
                stride *= sign;
                femurBase *= sign;
                tibiaBase *= sign;
                // A stopped gait supports the body on all six feet, even if
                // its phase froze during a swing half-cycle.
                if (gaitDrive < config.gaitStartThreshold)
                {
                    stance = true;
                    stanceProgress = .5f;
                    baseCoxa = stride = femurBase = tibiaBase = 0f;
                }
            }
            return new LegDriveTarget {
                baseAngles = new Vector3(baseCoxa, femurBase, tibiaBase),
                angles = new Vector3(stride + coxaOffsetDegrees, femurBase + femurOffsetDegrees, tibiaBase + tibiaOffsetDegrees),
                stance = stance, stanceProgress = stanceProgress
            };
        }

        // Single owner of stance and articulation command writes.
        public void ApplyDriveTargets(in LegDriveTarget target)
        {
            if (footAdhesion != null) footAdhesion.SetStance(target.stance, target.stanceProgress);
            LastBaseCoxaTarget = target.baseAngles.x;
            LastCorrectedCoxaTarget = target.angles.x;
            coxa.SetTarget(LastCorrectedCoxaTarget);
            LastBaseFemurTarget = target.baseAngles.y;
            LastCorrectedFemurTarget = target.angles.y;
            LastBaseTibiaTarget = target.baseAngles.z;
            LastCorrectedTibiaTarget = target.angles.z;
            femur.SetTarget(LastCorrectedFemurTarget);
            tibia.SetTarget(LastCorrectedTibiaTarget);
        }

        public void ApplyTrajectory(float globalPhase, in FlyMotorCommand motor, FlyLocomotionConfig config,
                                    float coxaOffsetDegrees = 0f, float femurOffsetDegrees = 0f, float tibiaOffsetDegrees = 0f,
                                    float stanceCoxaMultiplier = 1f, float steeringTurn = float.NaN)
        {
            var target = CalculateNominalTargets(globalPhase, motor, config, coxaOffsetDegrees, femurOffsetDegrees,
                                                tibiaOffsetDegrees, stanceCoxaMultiplier, steeringTurn);
            ApplyDriveTargets(target);
        }
    }
}
