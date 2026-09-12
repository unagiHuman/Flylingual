using UnityEngine;

namespace FlyLocomotionPoC
{
    [CreateAssetMenu(menuName = "FlyBrain/Fly Locomotion Config", fileName = "FlyLocomotionConfig")]
    public sealed class FlyLocomotionConfig : ScriptableObject
    {
        [Header("Thorax")]
        public float thoraxMass = 0.35f;
        public Vector3 thoraxSize = new Vector3(1.4f, 0.7f, 1.8f);
        public float thoraxLinearDamping = 0.25f;
        public float thoraxAngularDamping = 0.8f;

        [Header("Leg geometry")]
        public float coxaLength = 0.42f;
        public float femurLength = 0.76f;
        public float tibiaLength = 0.72f;
        public float coxaRadius = 0.11f;
        public float femurRadius = 0.10f;
        public float tibiaRadius = 0.08f;
        public float legMass = 0.035f;

        [Header("Articulation drives")]
        public float driveStiffness = 2600f;
        public float driveDamping = 160f;
        public float driveForceLimit = 850f;
        public float jointLowerLimit = -65f;
        public float jointUpperLimit = 65f;

        [Header("Tripod CPG")]
        // Opt-in for the candidate rig whose rest pose places the feet below
        // the knees. Existing serialized scenes retain their original gait.
        public bool groundedTripodGait = false;
        public float gaitFrequencyHz = 2.2f;
        public float coxaStrideAmplitudeDegrees = 22f;
        public float femurLiftAmplitudeDegrees = 20f;
        public float tibiaLiftAmplitudeDegrees = 28f;
        public float gaitStartThreshold = 0.03f;
        public float steeringGain = 0.5f;
        // Legacy scenes retain forward-only inner strides. Gameplay can opt in
        // to signed inner strides for sufficient differential turning authority.
        public float minimumSideScale = 0.15f;
        public float turnGaitContribution = 0.7f;
        public float turnSign = -1f;
        public float motorSmoothingSeconds = 0.12f;

        [Header("Diagnostics")]
        public float statusLogIntervalSeconds = 1f;

        public float SideScale(bool left, float turn)
        {
            float scale=left?1f-turnSign*turn*steeringGain:1f+turnSign*turn*steeringGain;
            return Mathf.Clamp(scale,minimumSideScale,1.85f);
        }

        private void OnValidate()
        {
            thoraxMass = Mathf.Max(0.01f, thoraxMass);
            thoraxSize = new Vector3(
                Mathf.Max(0.1f, thoraxSize.x),
                Mathf.Max(0.1f, thoraxSize.y),
                Mathf.Max(0.1f, thoraxSize.z));
            coxaLength = Mathf.Max(0.05f, coxaLength);
            femurLength = Mathf.Max(0.05f, femurLength);
            tibiaLength = Mathf.Max(0.05f, tibiaLength);
            coxaRadius = Mathf.Max(0.01f, coxaRadius);
            femurRadius = Mathf.Max(0.01f, femurRadius);
            tibiaRadius = Mathf.Max(0.01f, tibiaRadius);
            legMass = Mathf.Max(0.001f, legMass);
            driveStiffness = Mathf.Max(0f, driveStiffness);
            driveDamping = Mathf.Max(0f, driveDamping);
            driveForceLimit = Mathf.Max(0f, driveForceLimit);
            gaitFrequencyHz = Mathf.Max(0f, gaitFrequencyHz);
            motorSmoothingSeconds = Mathf.Max(0.001f, motorSmoothingSeconds);
            turnGaitContribution = Mathf.Clamp01(turnGaitContribution);
            statusLogIntervalSeconds = Mathf.Max(0.1f, statusLogIntervalSeconds);
            turnSign = Mathf.Approximately(turnSign, 0f) ? 1f : Mathf.Sign(turnSign);
        }
    }
}
