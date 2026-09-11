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

        public void ApplyTrajectory(float globalPhase, in FlyMotorCommand motor, FlyLocomotionConfig config,
                                    float coxaOffsetDegrees = 0f, float femurOffsetDegrees = 0f, float tibiaOffsetDegrees = 0f,
                                    float stanceCoxaMultiplier = 1f)
        {
            float legPhase = group == TripodGroup.A ? globalPhase : globalPhase + Mathf.PI;
            float strideWave = Mathf.Sin(legPhase);
            if (footAdhesion != null)
            {
                float stanceProgress = strideWave <= 0f
                    ? Mathf.Clamp01(Mathf.Repeat(legPhase - Mathf.PI, 2f * Mathf.PI) / Mathf.PI)
                    : 0f;
                footAdhesion.SetStance(strideWave <= 0f, stanceProgress);
            }
            float swingWave = Mathf.Max(0f, strideWave);
            float sideScale = config.SideScale(leftSide,motor.turn);

            // Turning must still produce a tripod gait when forward is zero.
            // The differential side scale supplies the yaw bias.
            float gaitDrive = Mathf.Max(Mathf.Abs(motor.forward), Mathf.Abs(motor.turn) * config.turnGaitContribution);
            float stride = -strideWave * config.coxaStrideAmplitudeDegrees * gaitDrive * sideScale;
            LastBaseCoxaTarget = stride;
            if (strideWave <= 0f)
            {
                stride *= Mathf.Max(1f, stanceCoxaMultiplier);
            }
            LastCorrectedCoxaTarget = stride + coxaOffsetDegrees;
            float lift = swingWave * gaitDrive;
            coxa.SetTarget(LastCorrectedCoxaTarget);
            LastBaseFemurTarget = lift * config.femurLiftAmplitudeDegrees;
            LastCorrectedFemurTarget = LastBaseFemurTarget + femurOffsetDegrees;
            LastBaseTibiaTarget = -lift * config.tibiaLiftAmplitudeDegrees;
            LastCorrectedTibiaTarget = LastBaseTibiaTarget + tibiaOffsetDegrees;
            femur.SetTarget(LastCorrectedFemurTarget);
            tibia.SetTarget(LastCorrectedTibiaTarget);
        }
    }
}
