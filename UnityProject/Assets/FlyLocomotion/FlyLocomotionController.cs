using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyLocomotionController : MonoBehaviour
    {
        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyMotorSource motorSource;
        [SerializeField] private FlyLocomotionConfig config;
        [SerializeField] private FlyLocalReflexLayer reflexLayer;
        [SerializeField] private float phase;

        private FlyMotorCommand currentMotor;
        private FlyMotorCommand targetMotor;

        public FlyMotorSource MotorSource => motorSource;
        public FlyLocalReflexLayer ReflexLayer => reflexLayer;
        public FlyMotorCommand CurrentMotor => currentMotor;
        public float Phase => phase;
        public float EffectivePhase => Mathf.Repeat(
            phase + (reflexLayer != null && reflexLayer.enabled ? reflexLayer.CurrentPhaseOffsetRadians : 0f),
            2f * Mathf.PI);
        public float LeftGaitScale => ComputeSideScale(true);
        public float RightGaitScale => ComputeSideScale(false);

        public void SetPhaseForDiagnostics(float phaseRadians)
        {
            phase = Mathf.Repeat(phaseRadians, 2f * Mathf.PI);
        }

        public void Configure(FlyBody body, FlyMotorSource source, FlyLocomotionConfig locomotionConfig)
        {
            flyBody = body;
            motorSource = source;
            config = locomotionConfig;
            currentMotor = FlyMotorCommand.Stop;
            targetMotor = FlyMotorCommand.Stop;
        }

        public void SetMotorSource(FlyMotorSource source)
        {
            motorSource = source;
        }

        public void SetReflexLayer(FlyLocalReflexLayer layer)
        {
            reflexLayer = layer;
        }

        public void ConfigureFootAdhesion(bool enabled, float normalStrength, float shearStrength,
                                          float attachDelay, float detachThreshold)
        {
            if (flyBody == null)
            {
                return;
            }

            float bodyWeight = flyBody.TotalMass * Physics.gravity.magnitude;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null)
                {
                    adhesion.ConfigureRuntime(enabled, bodyWeight, normalStrength, shearStrength, attachDelay, detachThreshold);
                }
            }
        }

        private void FixedUpdate()
        {
            if (flyBody == null || config == null)
            {
                return;
            }

            FlyMotorCommand rawMotor = motorSource == null ? FlyMotorCommand.Stop : motorSource.GetMotorCommand();
            targetMotor = reflexLayer != null && reflexLayer.enabled
                ? reflexLayer.Evaluate(rawMotor, phase, Time.fixedDeltaTime)
                : rawMotor;
            float smoothing = Mathf.Max(0.001f, config.motorSmoothingSeconds);
            float blend = Mathf.Clamp01(Time.fixedDeltaTime / smoothing);
            currentMotor = new FlyMotorCommand(
                Mathf.Lerp(currentMotor.forward, targetMotor.forward, blend),
                Mathf.Lerp(currentMotor.turn, targetMotor.turn, blend));

            float activity = Mathf.Max(currentMotor.forward, Mathf.Abs(currentMotor.turn) * 0.5f);
            if (activity > config.gaitStartThreshold)
            {
                phase += 2f * Mathf.PI * config.gaitFrequencyHz * Time.fixedDeltaTime;
                phase = Mathf.Repeat(phase, 2f * Mathf.PI);
            }

            float trajectoryPhase = EffectivePhase;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyLeg leg = flyBody.Legs[i];
                if (leg != null)
                {
                    float coxaOffset = 0f;
                    float femurOffset = 0f;
                    float tibiaOffset = 0f;
                    float stanceCoxaMultiplier = 1f;
                    if (reflexLayer != null && reflexLayer.enabled)
                    {
                        reflexLayer.GetJointOffsets(leg, trajectoryPhase, out coxaOffset, out femurOffset, out tibiaOffset);
                        stanceCoxaMultiplier = reflexLayer.GetStanceCoxaMultiplier(leg, trajectoryPhase);
                    }

                    leg.ApplyTrajectory(trajectoryPhase, currentMotor, config, coxaOffset, femurOffset, tibiaOffset, stanceCoxaMultiplier);
                }
            }
        }

        private float ComputeSideScale(bool left)
        {
            return config.SideScale(left,currentMotor.turn);
        }

        private void OnValidate()
        {
            if (config != null)
            {
                config.motorSmoothingSeconds = Mathf.Max(0.001f, config.motorSmoothingSeconds);
            }
        }
    }
}
