using UnityEngine;
using System.Collections.Generic;

namespace FlyLocomotionPoC
{
    public sealed class FlyLocomotionController : MonoBehaviour
    {
        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyMotorSource motorSource;
        [SerializeField] private FlyLocomotionConfig config;
        [SerializeField] private FlyLocalReflexLayer reflexLayer;
        [SerializeField] private float phase;

        // Diagnostic-only, runtime opt-in; never serialized into gameplay assets.
        public bool DiagnosticSeparateSteering { get; set; }
        public float TrajectoryTurn => DiagnosticSeparateSteering ? targetMotor.turn : currentMotor.turn;

        // No subscriber in normal gameplay; diagnostics observe without selecting targets.
        public event System.Action<FlyLeg, FlyLeg.LegDriveTarget> DiagnosticTargetObserved;
        public float DiagnosticJoinSeconds { get; set; }
        private bool wasActive;
        private float joinElapsed;
        private readonly Dictionary<FlyLeg, Vector3> joinOrigins = new Dictionary<FlyLeg, Vector3>();
        public static Vector3 BlendStartup(Vector3 origin, Vector3 nominal, float elapsed, float duration)
        {
            if (duration <= 0f || elapsed >= duration) return nominal;
            float u = Mathf.Clamp01(elapsed / duration);
            float w = u * u * u * (10f + u * (-15f + 6f * u));
            return Vector3.LerpUnclamped(origin, nominal, w);
        }
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
            wasActive = false; joinElapsed = 0f; joinOrigins.Clear();
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

            bool active = activity > config.gaitStartThreshold;
            if (DiagnosticJoinSeconds > 0f && active && !wasActive)
            {
                joinElapsed = 0f;
                joinOrigins.Clear();
                foreach (var leg in flyBody.Legs)
                    if (leg != null) joinOrigins[leg] = new Vector3(leg.Coxa.Target, leg.Femur.Target, leg.Tibia.Target);
            }
            if (!active) joinOrigins.Clear();
            wasActive = active;
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

                    var target = leg.CalculateNominalTargets(trajectoryPhase, currentMotor, config, coxaOffset, femurOffset, tibiaOffset, stanceCoxaMultiplier, TrajectoryTurn);
                    if (DiagnosticJoinSeconds > 0f && joinOrigins.TryGetValue(leg, out var origin))
                        target.angles = BlendStartup(origin, target.angles, joinElapsed, DiagnosticJoinSeconds);
                    DiagnosticTargetObserved?.Invoke(leg, target);
                    leg.ApplyDriveTargets(target);
                }
            }
            // Runtime diagnostic opt-in only; each foot otherwise retains its own FixedUpdate.
            foreach (var leg in flyBody.Legs)
                if (leg != null && leg.FootAdhesion != null) leg.FootAdhesion.EvaluateDiagnosticTick();
            joinElapsed += Time.fixedDeltaTime;
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
