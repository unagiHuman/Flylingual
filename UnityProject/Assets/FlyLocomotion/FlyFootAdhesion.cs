using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyFootAdhesion : MonoBehaviour
    {
        [SerializeField] private float adhesionNormalStrength = 0.35f;
        [SerializeField] private float adhesionShearStrength = 0.20f;
        [SerializeField] private float attachDelay = 0.02f;
        [SerializeField] private float detachThreshold = 1.25f;

        [SerializeField] private ArticulationBody footBody;
        [SerializeField] private FlyFootContact footContact;
        private bool adhesionEnabled;
        private bool stanceActive;
        private bool attached;
        private bool blockedUntilRelease;
        private float eligibleSeconds;
        private float bodyWeightNewtons;
        private float normalForceNewtons;
        private float shearForceNewtons;
        private float gripUtilization;
        private int attachmentCount;
        private int detachCount;
        private int contactTickCount;
        private int stanceTickCount;
        private int eligibleTickCount;
        private int swingDetachCount;
        private int contactLostDetachCount;
        private int shearOverloadDetachCount;
        private Vector3 lastAdhesionForce;
        private float lastNormalForceDot = 1f;
        private float currentAttachmentDuration;
        private float totalAttachmentDuration;
        private float maxAttachmentDuration;
        private float accumulatedNormalImpulse;
        private float accumulatedShearImpulse;
        private float peakNormalUtilization;
        private float peakShearUtilization;
        private float peakGripUtilization;
        private float stanceProgress;
        private float contactLostStanceProgressSum;
        private int contactLostStanceProgressCount;

        public bool DiagnosticDrivenByController { get; set; }

        // Read-only diagnostics of the inputs actually consumed by adhesion this tick.
        public float LastEvaluationFixedTime { get; private set; } = float.NegativeInfinity;
        public bool LastEvaluatedStance { get; private set; }
        public bool LastEvaluatedContact { get; private set; }
        public int LastEvaluatedHoldTicks { get; private set; }
        public bool Attached => attached;
        public float NormalForceNewtons => normalForceNewtons;
        public float ShearForceNewtons => shearForceNewtons;
        public float GripUtilization => gripUtilization;
        public int AttachmentCount => attachmentCount;
        public int DetachCount => detachCount;
        public int ContactTickCount => contactTickCount;
        public int StanceTickCount => stanceTickCount;
        public int EligibleTickCount => eligibleTickCount;
        public int SwingDetachCount => swingDetachCount;
        public int ContactLostDetachCount => contactLostDetachCount;
        public int ShearOverloadDetachCount => shearOverloadDetachCount;
        public float LastNormalForceDot => lastNormalForceDot;
        public float MeanAttachmentDuration => attachmentCount == 0 ? 0f : totalAttachmentDuration / attachmentCount;
        public float MaxAttachmentDuration => maxAttachmentDuration;
        public float AccumulatedNormalImpulse => accumulatedNormalImpulse;
        public float AccumulatedShearImpulse => accumulatedShearImpulse;
        public float PeakNormalUtilization => peakNormalUtilization;
        public float PeakShearUtilization => peakShearUtilization;
        public float PeakGripUtilization => peakGripUtilization;
        public float MeanContactLostStanceProgress => contactLostStanceProgressCount == 0
            ? -1f
            : contactLostStanceProgressSum / contactLostStanceProgressCount;

        public void Configure(ArticulationBody body, FlyFootContact contact)
        {
            footBody = body;
            footContact = contact;
        }

        public void ConfigureRuntime(bool enabled, float bodyWeight, float normalStrength, float shearStrength,
                                     float delay, float threshold)
        {
            adhesionEnabled = enabled;
            bodyWeightNewtons = Mathf.Max(0f, bodyWeight);
            adhesionNormalStrength = Mathf.Max(0f, normalStrength);
            adhesionShearStrength = Mathf.Max(0f, shearStrength);
            attachDelay = Mathf.Max(0f, delay);
            detachThreshold = Mathf.Max(0.01f, threshold);
            ResetState();
        }

        public void SetStance(bool stance, float progress)
        {
            stanceActive = stance;
            stanceProgress = Mathf.Clamp01(progress);
        }

        private void FixedUpdate()
        {
            if (!DiagnosticDrivenByController) EvaluateAdhesion();
        }

        public void EvaluateDiagnosticTick()
        {
            if (DiagnosticDrivenByController && isActiveAndEnabled) EvaluateAdhesion();
        }

        private void EvaluateAdhesion()
        {
            normalForceNewtons = 0f;
            shearForceNewtons = 0f;
            gripUtilization = 0f;

            bool validContact = footContact != null && footContact.HasFreshSurfaceContact;
            LastEvaluationFixedTime = Time.fixedTime;
            LastEvaluatedStance = stanceActive;
            LastEvaluatedContact = validContact;
            LastEvaluatedHoldTicks = footContact == null ? 0 : footContact.RemainingContactHoldTicks;
            if (footContact != null) footContact.AdvanceAdhesionTick();
            if (validContact) contactTickCount++;
            if (stanceActive) stanceTickCount++;
            if (validContact && stanceActive) eligibleTickCount++;
            if (!adhesionEnabled || !stanceActive || !validContact || footBody == null)
            {
                if (!stanceActive || !validContact)
                {
                    blockedUntilRelease = false;
                }
                if (attached && !stanceActive) swingDetachCount++;
                if (attached && stanceActive && !validContact)
                {
                    contactLostDetachCount++;
                    contactLostStanceProgressSum += stanceProgress;
                    contactLostStanceProgressCount++;
                }
                Detach(attached);
                return;
            }

            if (blockedUntilRelease)
            {
                return;
            }

            if (!attached)
            {
                eligibleSeconds += Time.fixedDeltaTime;
                if (eligibleSeconds + 0.0001f < attachDelay)
                {
                    return;
                }

                attached = true;
                attachmentCount++;
            }

            float maxNormal = bodyWeightNewtons * adhesionNormalStrength;
            float maxShear = bodyWeightNewtons * adhesionShearStrength;
            Vector3 normal = footContact.SurfaceNormal;
            Vector3 relativeVelocity = footContact.SurfaceRelativeVelocity;
            Vector3 tangentialVelocity = relativeVelocity - Vector3.Project(relativeVelocity, normal);
            Vector3 requiredShear = maxShear <= 0.0001f
                ? Vector3.zero
                : -tangentialVelocity * (footBody.mass / Mathf.Max(0.001f, Time.fixedDeltaTime));
            float requiredShearMagnitude = requiredShear.magnitude;
            float normalUtilization = maxNormal <= 0.0001f ? 0f : 1f;
            float loadRatio = maxShear <= 0.0001f ? 0f : requiredShearMagnitude / maxShear;
            float shearUtilization = loadRatio;
            peakNormalUtilization = Mathf.Max(peakNormalUtilization, normalUtilization);
            peakShearUtilization = Mathf.Max(peakShearUtilization, shearUtilization);
            peakGripUtilization = Mathf.Max(peakGripUtilization, Mathf.Max(normalUtilization, shearUtilization));
            if (loadRatio > detachThreshold)
            {
                blockedUntilRelease = true;
                shearOverloadDetachCount++;
                Detach(true);
                return;
            }

            Vector3 shearForce = Vector3.ClampMagnitude(requiredShear, maxShear);
            Vector3 normalForce = -normal * maxNormal;
            footBody.AddForceAtPosition(normalForce + shearForce, footContact.SurfaceContactPoint, ForceMode.Force);
            lastAdhesionForce = normalForce + shearForce;
            lastNormalForceDot = Vector3.Dot(normal.normalized, normalForce.normalized);
            normalForceNewtons = maxNormal;
            shearForceNewtons = shearForce.magnitude;
            gripUtilization = Mathf.Max(normalUtilization, shearUtilization);
            accumulatedNormalImpulse += normalForceNewtons * Time.fixedDeltaTime;
            accumulatedShearImpulse += shearForceNewtons * Time.fixedDeltaTime;
            currentAttachmentDuration += Time.fixedDeltaTime;
            totalAttachmentDuration += Time.fixedDeltaTime;
            maxAttachmentDuration = Mathf.Max(maxAttachmentDuration, currentAttachmentDuration);
        }

        private void Detach(bool counted)
        {
            if (attached && counted)
            {
                detachCount++;
            }

            attached = false;
            eligibleSeconds = 0f;
            currentAttachmentDuration = 0f;
        }

        private void ResetState()
        {
            attached = false;
            blockedUntilRelease = false;
            eligibleSeconds = 0f;
            normalForceNewtons = 0f;
            shearForceNewtons = 0f;
            gripUtilization = 0f;
            attachmentCount = 0;
            detachCount = 0;
            contactTickCount = 0;
            stanceTickCount = 0;
            eligibleTickCount = 0;
            swingDetachCount = 0;
            contactLostDetachCount = 0;
            shearOverloadDetachCount = 0;
            lastAdhesionForce = Vector3.zero;
            lastNormalForceDot = 1f;
            currentAttachmentDuration = 0f;
            totalAttachmentDuration = 0f;
            maxAttachmentDuration = 0f;
            accumulatedNormalImpulse = 0f;
            accumulatedShearImpulse = 0f;
            peakNormalUtilization = 0f;
            peakShearUtilization = 0f;
            peakGripUtilization = 0f;
            stanceProgress = 0f;
            contactLostStanceProgressSum = 0f;
            contactLostStanceProgressCount = 0;
        }

        private void OnDrawGizmosSelected()
        {
            if (footContact == null || !footContact.HasFreshSurfaceContact) return;
            Vector3 point = footContact.SurfaceContactPoint;
            Gizmos.color = Color.red;
            Gizmos.DrawLine(point, point + footContact.SurfaceNormal * 0.2f);
            Gizmos.color = Color.blue;
            Vector3 forceDirection = lastAdhesionForce.sqrMagnitude > 0.000001f
                ? lastAdhesionForce.normalized
                : -footContact.SurfaceNormal;
            Gizmos.DrawLine(point, point + forceDirection * 0.2f);
        }
    }
}
