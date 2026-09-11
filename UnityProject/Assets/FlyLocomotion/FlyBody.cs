using System.Collections.Generic;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyBody : MonoBehaviour
    {
        [SerializeField] private ArticulationBody thorax;
        [SerializeField] private FlyLocomotionConfig config;
        [SerializeField] private FlyLeg[] legs = new FlyLeg[0];

        public ArticulationBody Thorax => thorax;
        public FlyLocomotionConfig Config => config;
        public IReadOnlyList<FlyLeg> Legs => legs;
        public float TotalMass
        {
            get
            {
                float mass = thorax == null ? 0f : thorax.mass;
                for (int i = 0; i < legs.Length; i++)
                {
                    if (legs[i] == null) continue;
                    mass += GetMass(legs[i].Coxa);
                    mass += GetMass(legs[i].Femur);
                    mass += GetMass(legs[i].Tibia);
                }

                return mass;
            }
        }

        public void Configure(ArticulationBody root, FlyLocomotionConfig locomotionConfig, FlyLeg[] configuredLegs)
        {
            thorax = root;
            config = locomotionConfig;
            legs = configuredLegs ?? new FlyLeg[0];
        }

        public int GroundContactCount
        {
            get
            {
                int count = 0;
                for (int i = 0; i < legs.Length; i++)
                {
                    if (legs[i] != null && legs[i].IsGrounded) count++;
                }

                return count;
            }
        }

        public Vector3 Position => thorax == null ? transform.position : thorax.transform.position;
        public Vector3 LinearVelocity => thorax == null ? Vector3.zero : thorax.linearVelocity;
        public Vector3 AngularVelocity => thorax == null ? Vector3.zero : thorax.angularVelocity;
        public Vector3 FirstFootProbePosition => legs.Length == 0 || legs[0] == null ? Vector3.zero : legs[0].FootProbePosition;

        private static float GetMass(FlyJoint joint)
        {
            ArticulationBody body = joint == null ? null : joint.GetComponent<ArticulationBody>();
            return body == null ? 0f : body.mass;
        }
    }
}
