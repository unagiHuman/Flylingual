using UnityEngine;

namespace FlyLocomotionPoC
{
    [DisallowMultipleComponent]
    public sealed class FlyJoint : MonoBehaviour
    {
        [SerializeField] private ArticulationBody articulation;
        [SerializeField] private float lowerLimit = -65f;
        [SerializeField] private float upperLimit = 65f;
        [SerializeField] private float target;

        public ArticulationBody Articulation => articulation;
        public float Target => target;

        public void Configure(ArticulationBody body, FlyLocomotionConfig config, Vector3 parentAnchor)
        {
            articulation = body;
            lowerLimit = config.jointLowerLimit;
            upperLimit = config.jointUpperLimit;

            articulation.jointType = ArticulationJointType.RevoluteJoint;
            articulation.anchorPosition = Vector3.zero;
            articulation.parentAnchorPosition = parentAnchor;
            articulation.mass = config.legMass;
            articulation.linearDamping = 0.15f;
            articulation.angularDamping = 0.25f;

            var drive = articulation.xDrive;
            drive.lowerLimit = lowerLimit;
            drive.upperLimit = upperLimit;
            drive.stiffness = config.driveStiffness;
            drive.damping = config.driveDamping;
            drive.forceLimit = config.driveForceLimit;
            drive.target = 0f;
            articulation.xDrive = drive;
            target = 0f;
        }

        public void SetTarget(float nextTarget)
        {
            target = Mathf.Clamp(nextTarget, lowerLimit, upperLimit);
            var drive = articulation.xDrive;
            drive.target = target;
            articulation.xDrive = drive;
        }
    }
}
