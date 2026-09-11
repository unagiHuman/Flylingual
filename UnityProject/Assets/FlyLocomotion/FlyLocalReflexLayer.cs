using System;
using System.Collections.Generic;
using UnityEngine;

namespace FlyLocomotionPoC
{
    /// <summary>
    /// Small, local terrain reflexes layered between the decoded motor command
    /// and the existing CPG.  The layer never writes the thorax pose or force;
    /// it only adjusts the command/phase presented to the existing gait.
    /// </summary>
    public sealed class FlyLocalReflexLayer : MonoBehaviour
    {
        private enum PhaseEscapeState
        {
            Idle,
            BlendIn,
            Hold,
            BlendOut
        }

        private enum RearStepUpState
        {
            Idle,
            WaitingForRearSwing,
            StepUp,
            RearPropulsion,
            Recovery
        }

        [Header("Phase escape")]
        [SerializeField] private float phaseEscapeDegrees = 45f;
        [SerializeField] private float phaseEscapeBlendSeconds = 0.12f;
        [SerializeField] private float phaseEscapeHoldSeconds = 0.12f;
        [SerializeField] private float phaseBadRegionDegrees = 45f;
        [SerializeField] private float phaseEscapeCooldownSeconds = 1f;
        [SerializeField] private float phaseEscapeMinObstacleHeight = 0.025f;
        [SerializeField] private float phaseEscapeMaxObstacleHeight = 0.040f;

        [Header("Shared stall detection")]
        [SerializeField] private float rawForwardMinimum = 0.1f;
        [SerializeField] private float stallVelocityThresholdMps = 0.08f;
        [SerializeField] private float stallDetectionSeconds = 0.18f;

        [Header("Rear-leg step-up reflex")]
        [SerializeField] private float rearFollowStallSeconds = 0.25f;
        [SerializeField] private float rearStepUpMaxSeconds = 6f;
        [SerializeField] private float rearStepUpCooldownSeconds = 1f;
        [SerializeField] private float rearStepUpBlendSeconds = 0.12f;
        [SerializeField] private float rearStepUpCoxaOffsetDegrees = -10f;
        [SerializeField] private float rearStepUpFemurOffsetDegrees = 7f;
        [SerializeField] private float rearStepUpTibiaOffsetDegrees = -10f;
        [SerializeField] private float rearStepUpMinObstacleHeight = 0.04f;
        [SerializeField] private float rearStepUpMaxObstacleHeight = 0.06f;

        [Header("Rear-leg stance propulsion reflex")]
        [SerializeField] private float rearStanceCoxaMultiplier = 1.35f;
        [SerializeField] private float rearPropulsionBlendSeconds = 0.06f;
        [SerializeField] private float rearPropulsionMaxSeconds = 0.6f;
        [SerializeField] private float rearPropulsionContactLossGraceSeconds = 0.08f;
        [SerializeField] private float rearPropulsionTriggerMaxForwardVelocityMps = 0.3f;
        [SerializeField] private float rearPropulsionReleaseForwardVelocityMps = 0.4f;

        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyStepObstacle obstacle;

        private bool phaseEscapeEnabled;
        private bool rearFollowAssistEnabled;
        private bool rearPropulsionEnabled;
        private PhaseEscapeState phaseEscapeState;
        private float currentPhaseOffsetRadians;
        private float phaseEscapeHoldRemaining;
        private float phaseEscapeCooldownRemaining;
        private float phaseEscapeStallTimer;
        private int observedTopContactEvents;
        private bool phaseBadRegionObserved;
        private bool phaseEscapeUsedForStall;

        private bool rearStepUpEnabled;
        private RearStepUpState rearStepUpState;
        private FlyLeg activeRearLeg;
        private FlyLeg propulsionCandidateRearLeg;
        private float rearStepUpCooldownRemaining;
        private float rearFollowStallTimer;
        private float rearStepUpElapsed;
        private float rearStepUpBlend;
        private bool rearStepUpUsedForEncounter;
        private float rearPropulsionBlend;
        private float rearPropulsionElapsed;
        private float rearPropulsionContactLostSeconds;
        private float rearPropulsionActiveSeconds;
        private bool rearPropulsionStanceObserved;
        private bool rearPropulsionUsedForEncounter;

        public FlyMotorCommand RawMotor { get; private set; } = FlyMotorCommand.Stop;
        public FlyMotorCommand EffectiveMotor { get; private set; } = FlyMotorCommand.Stop;
        public bool PhaseEscapeActive => phaseEscapeState != PhaseEscapeState.Idle;
        public bool RearStepUpActive => rearStepUpState == RearStepUpState.StepUp;
        public bool RearPropulsionActive => rearStepUpState == RearStepUpState.RearPropulsion;
        public string RearStepUpStateName => rearStepUpState.ToString();
        public string ActiveRearLegId => activeRearLeg == null ? string.Empty : activeRearLeg.LegId;
        public float RearStepUpCoxaOffsetAppliedDegrees => rearStepUpCoxaOffsetDegrees * rearStepUpBlend;
        public float RearStepUpFemurOffsetAppliedDegrees => rearStepUpFemurOffsetDegrees * rearStepUpBlend;
        public float RearStepUpTibiaOffsetAppliedDegrees => rearStepUpTibiaOffsetDegrees * rearStepUpBlend;
        public float RearStepUpBlend => rearStepUpBlend;
        public float RearStanceCoxaMultiplier => 1f + (Mathf.Max(1f, rearStanceCoxaMultiplier) - 1f) * rearPropulsionBlend;
        public float RearPropulsionBlend => rearPropulsionBlend;
        public float CurrentPhaseOffsetRadians => currentPhaseOffsetRadians;
        public float CurrentPhaseOffsetDegrees => currentPhaseOffsetRadians * Mathf.Rad2Deg;
        public float RawForward => RawMotor.forward;
        public float EffectiveForward => EffectiveMotor.forward;
        public float PhaseEscapeStallTimer => phaseEscapeStallTimer;
        public float RearFollowStallTimer => rearFollowStallTimer;
        public float PropulsionAssistDurationSeconds => rearPropulsionActiveSeconds;
        public int PhaseEscapeActivationCount { get; private set; }
        public int RearStepUpActivationCount { get; private set; }
        public int PropulsionAssistActivationCount { get; private set; }
        public float PhaseEscapeOffsetAppliedDegrees { get; private set; }
        public float PhaseEscapePhaseBeforeDegrees { get; private set; } = -1f;
        public float PhaseEscapePhaseAfterDegrees { get; private set; } = -1f;
        public float LastPhaseEscapeActivationTime { get; private set; } = -1f;
        public float LastRearStepUpActivationTime { get; private set; } = -1f;
        public float LastPropulsionAssistActivationTime { get; private set; } = -1f;
        public bool PropulsionAssistActive => RearPropulsionActive;
        public bool RearSupportPresent => HasRearTopContact();
        public bool FrontOrMiddleTopContact => HasFrontOrMiddleTopContact();

        public void Configure(FlyBody body, FlyStepObstacle step)
        {
            flyBody = body;
            obstacle = step;
        }

        public void ConfigureMode(string mode)
        {
            string normalized = string.IsNullOrEmpty(mode) ? "NONE" : mode.Trim().ToUpperInvariant();
            phaseEscapeEnabled = normalized == "A" || normalized == "BOTH";
            rearStepUpEnabled = normalized == "B" || normalized == "BOTH";
            rearPropulsionEnabled = rearStepUpEnabled && normalized != "B_STEP_ONLY";
            if (normalized == "B_STEP_ONLY")
            {
                rearStepUpEnabled = true;
            }
        }

        public void ResetState()
        {
            RawMotor = FlyMotorCommand.Stop;
            EffectiveMotor = FlyMotorCommand.Stop;
            phaseEscapeState = PhaseEscapeState.Idle;
            currentPhaseOffsetRadians = 0f;
            phaseEscapeHoldRemaining = 0f;
            phaseEscapeCooldownRemaining = 0f;
            phaseEscapeStallTimer = 0f;
            observedTopContactEvents = 0;
            phaseBadRegionObserved = false;
            phaseEscapeUsedForStall = false;
            rearStepUpState = RearStepUpState.Idle;
            activeRearLeg = null;
            propulsionCandidateRearLeg = null;
            rearStepUpCooldownRemaining = 0f;
            rearFollowStallTimer = 0f;
            rearStepUpElapsed = 0f;
            rearStepUpBlend = 0f;
            rearStepUpUsedForEncounter = false;
            rearPropulsionBlend = 0f;
            rearPropulsionElapsed = 0f;
            rearPropulsionContactLostSeconds = 0f;
            rearPropulsionActiveSeconds = 0f;
            rearPropulsionStanceObserved = false;
            rearPropulsionUsedForEncounter = false;
            PhaseEscapeActivationCount = 0;
            RearStepUpActivationCount = 0;
            PropulsionAssistActivationCount = 0;
            PhaseEscapeOffsetAppliedDegrees = 0f;
            PhaseEscapePhaseBeforeDegrees = -1f;
            PhaseEscapePhaseAfterDegrees = -1f;
            LastPhaseEscapeActivationTime = -1f;
            LastRearStepUpActivationTime = -1f;
            LastPropulsionAssistActivationTime = -1f;
        }

        public FlyMotorCommand Evaluate(FlyMotorCommand rawMotor, float basePhaseRadians, float deltaSeconds)
        {
            float dt = Mathf.Max(0f, deltaSeconds);
            RawMotor = rawMotor;

            UpdatePhaseEscape(rawMotor, basePhaseRadians, dt);
            UpdateRearStepUp(rawMotor, basePhaseRadians, dt);

            // The reflex is local to one rear leg.  The decoded motor command
            // remains untouched so diagnostics can distinguish brain output
            // from joint-level terrain feedback.
            EffectiveMotor = rawMotor;
            return EffectiveMotor;
        }

        private void UpdatePhaseEscape(FlyMotorCommand rawMotor, float basePhaseRadians, float dt)
        {
            phaseEscapeCooldownRemaining = Mathf.Max(0f, phaseEscapeCooldownRemaining - dt);

            int topContacts = obstacle == null ? 0 : obstacle.TopContactEvents;
            bool hasTopContact = topContacts > 0;
            bool slow = IsStalled();
            if (topContacts > observedTopContactEvents && IsBadPhase(basePhaseRadians))
            {
                phaseBadRegionObserved = true;
            }

            observedTopContactEvents = topContacts;
            if (hasTopContact && slow && rawMotor.forward >= rawForwardMinimum)
            {
                phaseEscapeStallTimer += dt;
                if (IsBadPhase(basePhaseRadians))
                {
                    phaseBadRegionObserved = true;
                }
            }
            else
            {
                phaseEscapeStallTimer = 0f;
                phaseBadRegionObserved = false;
                if (phaseEscapeState == PhaseEscapeState.Idle)
                {
                    phaseEscapeUsedForStall = false;
                }
            }

            if (phaseEscapeEnabled && phaseEscapeState == PhaseEscapeState.Idle &&
                !phaseEscapeUsedForStall && phaseEscapeCooldownRemaining <= 0f &&
                rawMotor.forward >= rawForwardMinimum && hasTopContact && slow &&
                phaseEscapeStallTimer >= stallDetectionSeconds &&
                IsPhaseEscapeHeight() &&
                (phaseBadRegionObserved || IsBadPhase(basePhaseRadians)))
            {
                phaseEscapeUsedForStall = true;
                phaseEscapeState = PhaseEscapeState.BlendIn;
                PhaseEscapeActivationCount++;
                LastPhaseEscapeActivationTime = Time.unscaledTime;
                PhaseEscapePhaseBeforeDegrees = RepeatDegrees(basePhaseRadians * Mathf.Rad2Deg);
                PhaseEscapePhaseAfterDegrees = RepeatDegrees(PhaseEscapePhaseBeforeDegrees + phaseEscapeDegrees);
                Debug.Log("FLY_REFLEX_PHASE_ESCAPE_TRIGGER phaseBefore=" + PhaseEscapePhaseBeforeDegrees.ToString("0.###") +
                          " offsetDegrees=" + phaseEscapeDegrees.ToString("0.###") +
                          " topContacts=" + topContacts);
            }

            UpdatePhaseEscapeOffset(dt);
        }

        private void UpdatePhaseEscapeOffset(float dt)
        {
            if (phaseEscapeState == PhaseEscapeState.Idle)
            {
                currentPhaseOffsetRadians = Mathf.MoveTowards(currentPhaseOffsetRadians, 0f, OffsetStep(dt));
                return;
            }

            if (!IsStalled() && phaseEscapeState != PhaseEscapeState.BlendOut)
            {
                phaseEscapeState = PhaseEscapeState.BlendOut;
            }

            if (phaseEscapeState == PhaseEscapeState.BlendIn)
            {
                float target = phaseEscapeDegrees * Mathf.Deg2Rad;
                currentPhaseOffsetRadians = Mathf.MoveTowards(currentPhaseOffsetRadians, target, OffsetStep(dt));
                PhaseEscapeOffsetAppliedDegrees = Mathf.Max(PhaseEscapeOffsetAppliedDegrees, Mathf.Abs(CurrentPhaseOffsetDegrees));
                if (Mathf.Approximately(currentPhaseOffsetRadians, target))
                {
                    phaseEscapeState = PhaseEscapeState.Hold;
                    phaseEscapeHoldRemaining = phaseEscapeHoldSeconds;
                }
            }
            else if (phaseEscapeState == PhaseEscapeState.Hold)
            {
                PhaseEscapeOffsetAppliedDegrees = Mathf.Max(PhaseEscapeOffsetAppliedDegrees, Mathf.Abs(CurrentPhaseOffsetDegrees));
                phaseEscapeHoldRemaining -= dt;
                if (phaseEscapeHoldRemaining <= 0f)
                {
                    phaseEscapeState = PhaseEscapeState.BlendOut;
                }
            }
            else if (phaseEscapeState == PhaseEscapeState.BlendOut)
            {
                currentPhaseOffsetRadians = Mathf.MoveTowards(currentPhaseOffsetRadians, 0f, OffsetStep(dt));
                if (Mathf.Approximately(currentPhaseOffsetRadians, 0f))
                {
                    phaseEscapeState = PhaseEscapeState.Idle;
                    phaseEscapeCooldownRemaining = phaseEscapeCooldownSeconds;
                }
            }
        }

        private void UpdateRearStepUp(FlyMotorCommand rawMotor, float basePhaseRadians, float dt)
        {
            rearStepUpCooldownRemaining = Mathf.Max(0f, rearStepUpCooldownRemaining - dt);
            bool frontMiddleTop = HasFrontOrMiddleTopContact();
            bool rearTop = HasRearTopContact();
            if (rearPropulsionEnabled && !rearPropulsionUsedForEncounter && HasTopContact(propulsionCandidateRearLeg) &&
                rearStepUpState != RearStepUpState.RearPropulsion &&
                Mathf.Abs(flyBody.LinearVelocity.x) <= rearPropulsionTriggerMaxForwardVelocityMps)
            {
                activeRearLeg = propulsionCandidateRearLeg;
                StartRearPropulsion(rawMotor);
            }
            bool candidate = rawMotor.forward >= rawForwardMinimum &&
                             frontMiddleTop &&
                             !rearTop &&
                             IsStalled() &&
                             IsRearStepUpHeight();

            if (candidate)
            {
                rearFollowStallTimer += dt;
            }
            else
            {
                rearFollowStallTimer = 0f;
            }

            if (!frontMiddleTop || rearTop)
            {
                rearStepUpUsedForEncounter = false;
            }

            if (rearStepUpState == RearStepUpState.Idle)
            {
                rearStepUpBlend = Mathf.MoveTowards(rearStepUpBlend, 0f, BlendStep(dt));
                if (rearStepUpEnabled && !rearStepUpUsedForEncounter && rearStepUpCooldownRemaining <= 0f &&
                    candidate && rearFollowStallTimer >= rearFollowStallSeconds)
                {
                    rearStepUpUsedForEncounter = true;
                    rearStepUpState = RearStepUpState.WaitingForRearSwing;
                    activeRearLeg = null;
                    propulsionCandidateRearLeg = null;
                    rearPropulsionUsedForEncounter = false;
                    rearStepUpElapsed = 0f;
                    RearStepUpActivationCount++;
                    LastRearStepUpActivationTime = Time.unscaledTime;
                    Debug.Log("FLY_REFLEX_REAR_STEP_UP_TRIGGER rawForward=" + rawMotor.forward.ToString("0.###") +
                              " coxaOffset=" + rearStepUpCoxaOffsetDegrees.ToString("0.###") +
                              " femurOffset=" + rearStepUpFemurOffsetDegrees.ToString("0.###") +
                              " tibiaOffset=" + rearStepUpTibiaOffsetDegrees.ToString("0.###") +
                              " frontMiddleTop=true rearTop=false");
                }

                return;
            }

            rearStepUpElapsed += dt;
            bool activeRearTop = HasTopContact(activeRearLeg);
            if ((rearStepUpState == RearStepUpState.WaitingForRearSwing || rearStepUpState == RearStepUpState.StepUp) &&
                rearStepUpElapsed >= rearStepUpMaxSeconds)
            {
                rearStepUpState = RearStepUpState.Recovery;
            }
            else if (rearStepUpState == RearStepUpState.WaitingForRearSwing)
            {
                activeRearLeg = FindRearSwingLeg(basePhaseRadians);
                if (activeRearLeg != null)
                {
                    propulsionCandidateRearLeg = activeRearLeg;
                    rearStepUpState = RearStepUpState.StepUp;
                }
            }
            else if (rearStepUpState == RearStepUpState.StepUp)
            {
                rearStepUpBlend = Mathf.MoveTowards(rearStepUpBlend, 1f, BlendStep(dt));
                if (activeRearTop && Mathf.Abs(flyBody.LinearVelocity.x) <= rearPropulsionTriggerMaxForwardVelocityMps)
                {
                    StartRearPropulsion(rawMotor);
                }
                else if (activeRearLeg == null || !IsSwing(activeRearLeg, basePhaseRadians))
                {
                    activeRearLeg = null;
                    rearStepUpState = RearStepUpState.WaitingForRearSwing;
                }
            }
            else if (rearStepUpState == RearStepUpState.RearPropulsion)
            {
                rearStepUpBlend = Mathf.MoveTowards(rearStepUpBlend, 0f, BlendStep(dt));
                rearPropulsionElapsed += dt;
                rearPropulsionActiveSeconds += dt;
                rearPropulsionBlend = Mathf.MoveTowards(rearPropulsionBlend, 1f, RearPropulsionBlendStep(dt));
                bool stance = activeRearLeg != null && !IsSwing(activeRearLeg, basePhaseRadians);
                rearPropulsionStanceObserved |= stance;
                rearPropulsionContactLostSeconds = HasCurrentTopContact(activeRearLeg)
                    ? 0f
                    : rearPropulsionContactLostSeconds + dt;
                bool recovered = flyBody != null && flyBody.LinearVelocity.x >= rearPropulsionReleaseForwardVelocityMps;
                bool stanceEnded = rearPropulsionStanceObserved && !stance;
                if (recovered || stanceEnded || rearPropulsionElapsed >= rearPropulsionMaxSeconds ||
                    rearPropulsionContactLostSeconds >= rearPropulsionContactLossGraceSeconds)
                {
                    rearStepUpState = RearStepUpState.Recovery;
                }
            }
            else if (rearStepUpState == RearStepUpState.Recovery)
            {
                rearStepUpBlend = Mathf.MoveTowards(rearStepUpBlend, 0f, BlendStep(dt));
                rearPropulsionBlend = Mathf.MoveTowards(rearPropulsionBlend, 0f, RearPropulsionBlendStep(dt));
                if (Mathf.Approximately(rearStepUpBlend, 0f) && Mathf.Approximately(rearPropulsionBlend, 0f))
                {
                    rearStepUpState = RearStepUpState.Idle;
                    activeRearLeg = null;
                    rearStepUpCooldownRemaining = rearStepUpCooldownSeconds;
                }
            }
        }

        private void StartRearPropulsion(FlyMotorCommand rawMotor)
        {
            rearStepUpState = RearStepUpState.RearPropulsion;
            rearPropulsionElapsed = 0f;
            rearPropulsionContactLostSeconds = 0f;
            rearPropulsionStanceObserved = false;
            PropulsionAssistActivationCount++;
            rearPropulsionUsedForEncounter = true;
            LastPropulsionAssistActivationTime = Time.unscaledTime;
            Debug.Log("FLY_REFLEX_REAR_PROPULSION_TRIGGER leg=" + ActiveRearLegId +
                      " rawForward=" + rawMotor.forward.ToString("0.###") +
                      " multiplier=" + rearStanceCoxaMultiplier.ToString("0.###") +
                      " thoraxForwardVelocity=" + flyBody.LinearVelocity.x.ToString("0.###"));
        }

        public void GetJointOffsets(FlyLeg leg, float phaseRadians, out float coxaOffset, out float femurOffset, out float tibiaOffset)
        {
            coxaOffset = 0f;
            femurOffset = 0f;
            tibiaOffset = 0f;
            if (leg == null || rearStepUpState != RearStepUpState.StepUp || leg != activeRearLeg ||
                !IsSwing(leg, phaseRadians))
            {
                return;
            }

            coxaOffset = rearStepUpCoxaOffsetDegrees * rearStepUpBlend;
            femurOffset = rearStepUpFemurOffsetDegrees * rearStepUpBlend;
            tibiaOffset = rearStepUpTibiaOffsetDegrees * rearStepUpBlend;
        }

        public float GetStanceCoxaMultiplier(FlyLeg leg, float phaseRadians)
        {
            if (leg == null || leg != activeRearLeg || rearStepUpState != RearStepUpState.RearPropulsion ||
                IsSwing(leg, phaseRadians))
            {
                return 1f;
            }

            return RearStanceCoxaMultiplier;
        }

        private FlyLeg FindRearSwingLeg(float phaseRadians)
        {
            FlyLeg best = null;
            float bestSwingAmount = 0f;
            IReadOnlyList<FlyLeg> legs = flyBody == null ? null : flyBody.Legs;
            if (legs == null)
            {
                return null;
            }

            for (int i = 0; i < legs.Count; i++)
            {
                FlyLeg leg = legs[i];
                if (leg == null || !leg.LegId.EndsWith("H", StringComparison.Ordinal))
                {
                    continue;
                }

                float legPhase = leg.Group == FlyLeg.TripodGroup.A ? phaseRadians : phaseRadians + Mathf.PI;
                float swingAmount = Mathf.Sin(legPhase);
                if (swingAmount > bestSwingAmount)
                {
                    best = leg;
                    bestSwingAmount = swingAmount;
                }
            }

            return best;
        }

        private static bool IsSwing(FlyLeg leg, float phaseRadians)
        {
            float legPhase = leg.Group == FlyLeg.TripodGroup.A ? phaseRadians : phaseRadians + Mathf.PI;
            return Mathf.Sin(legPhase) > 0f;
        }

        private float BlendStep(float dt)
        {
            return dt / Mathf.Max(0.001f, rearStepUpBlendSeconds);
        }

        private float RearPropulsionBlendStep(float dt)
        {
            return dt / Mathf.Max(0.001f, rearPropulsionBlendSeconds);
        }

        private bool HasTopContact(FlyLeg leg)
        {
            return obstacle != null && leg != null && obstacle.GetTopLegEventsForLeg(leg.LegId) > 0;
        }

        private bool HasCurrentTopContact(FlyLeg leg)
        {
            return obstacle != null && leg != null &&
                   obstacle.TryGetLegContactSnapshot(leg.LegId, out FlyStepObstacle.LegContactSnapshot snapshot) &&
                   snapshot.top;
        }

        private bool HasFrontOrMiddleTopContact()
        {
            return obstacle != null &&
                   (obstacle.GetTopLegEvents("F") > 0 || obstacle.GetTopLegEvents("M") > 0);
        }

        private bool HasRearTopContact()
        {
            return obstacle != null && obstacle.GetTopLegEvents("H") > 0;
        }

        private bool IsStalled()
        {
            return flyBody != null && Mathf.Abs(flyBody.LinearVelocity.x) < stallVelocityThresholdMps;
        }

        private bool IsPhaseEscapeHeight()
        {
            return obstacle != null &&
                   obstacle.ObstacleHeight >= phaseEscapeMinObstacleHeight &&
                   obstacle.ObstacleHeight <= phaseEscapeMaxObstacleHeight;
        }

        private bool IsRearStepUpHeight()
        {
            return obstacle != null &&
                   obstacle.ObstacleHeight >= rearStepUpMinObstacleHeight &&
                   obstacle.ObstacleHeight <= rearStepUpMaxObstacleHeight;
        }

        private bool IsBadPhase(float phaseRadians)
        {
            float degrees = RepeatDegrees(phaseRadians * Mathf.Rad2Deg);
            return degrees <= phaseBadRegionDegrees || degrees >= 360f - phaseBadRegionDegrees;
        }

        private float OffsetStep(float deltaSeconds)
        {
            float blendSeconds = Mathf.Max(0.001f, phaseEscapeBlendSeconds);
            return Mathf.Abs(phaseEscapeDegrees) * Mathf.Deg2Rad * deltaSeconds / blendSeconds;
        }

        private static float RepeatDegrees(float degrees)
        {
            return Mathf.Repeat(degrees, 360f);
        }
    }
}
