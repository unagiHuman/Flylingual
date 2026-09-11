using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using FlyBrainPoC;
using UnityEngine;

namespace FlyLocomotionPoC
{
    [Serializable]
    public sealed class FlyFootAdhesionDiagnostic
    {
        public string legId;
        public string footColliderEntityId;
        public bool attachedArticulationBodyMatches;
        public string otherCollider;
        public int contactEnterCount;
        public int contactStayCount;
        public int contactExitCount;
        public int stanceTicks;
        public int contactTicks;
        public int stanceContactTicks;
        public int attachCount;
        public int detachCount;
        public int detachSwingCount;
        public int detachContactLostCount;
        public int detachShearOverloadCount;
        public float meanAttachmentDurationSeconds;
        public float maxAttachmentDurationSeconds;
        public float normalAdhesionImpulseNs;
        public float shearAdhesionImpulseNs;
        public float peakNormalUtilization;
        public float peakShearUtilization;
        public float peakGripUtilization;
        public float meanContactLostStanceProgress;
        public float normalForceDot;
    }

    [Serializable]
    public sealed class FlyStepObstacleTrialResult
    {
        public int protocolVersion = 1;
        public int trialId;
        public string source;
        public string action;
        public string frameRecordPath;
        public int recordedFrameCount;
        public float mockForward;
        public float initialPhaseDegrees;
        public float firstObstacleContactPhaseDegrees = -1f;
        public float obstacleHeight;
        public bool success;
        public string failureMode;
        public float timeToContactSeconds = -1f;
        public float timeToClearSeconds = -1f;
        public float totalTrialSeconds;
        public Vector3 rootStartPosition;
        public Vector3 rootFinalPosition;
        public Vector3 finalRootVelocity;
        public float worldDisplacementMeters;
        public float forwardDisplacementMeters;
        public float averageForwardVelocityMps;
        public float averageYawRateDegreesPerSecond;
        public float approachVelocityMps;
        public float finalPitchDegrees;
        public float finalRollDegrees;
        public float finalYawDegrees;
        public float maxAbsPitchDegrees;
        public float maxAbsRollDegrees;
        public float stalledSeconds;
        public bool fallDetected;
        public bool timeout;
        public bool reflexEnabled;
        public string reflexMode;
        public bool adhesionEnabled;
        public float adhesionNormalStrength;
        public float adhesionShearStrength;
        public float adhesionAttachDelay;
        public float adhesionDetachThreshold;
        public int adhesionAttachmentCount;
        public int adhesionDetachCount;
        public int adhesionContactTickCount;
        public int adhesionStanceTickCount;
        public int attachedFeetAtFinish;
        public float peakTotalGripUtilization;
        public FlyFootAdhesionDiagnostic[] footAdhesionDiagnostics;
        public int articulationDofCount;
        public FlyMetricStatistic rawForward;
        public FlyMetricStatistic effectiveForward;
        public int phaseEscapeActivationCount;
        public float phaseEscapeActivationTimeSeconds = -1f;
        public float phaseEscapeOffsetAppliedDegrees;
        public float phaseEscapePhaseBeforeDegrees = -1f;
        public float phaseEscapePhaseAfterDegrees = -1f;
        public int propulsionAssistActivationCount;
        public float propulsionAssistActivationTimeSeconds = -1f;
        public float propulsionAssistDurationSeconds;
        public bool propulsionAssistActiveAtFinish;
        public int rearStepUpActivationCount;
        public float rearStepUpActivationTimeSeconds = -1f;
        public string rearStepUpState;
        public string activeRearLeg;
        public float rearStepUpCoxaOffsetAppliedDegrees;
        public float rearStepUpFemurOffsetAppliedDegrees;
        public float rearStepUpTibiaOffsetAppliedDegrees;
        public float rearStepUpBlend;
        public bool rearSupportPresentAtFinish;
        public int frontObstacleContactEvents;
        public int topObstacleContactEvents;
        public float frontObstacleContactSeconds;
        public float topObstacleContactSeconds;
        public int frontLegObstacleContactEvents;
        public int middleLegObstacleContactEvents;
        public int rearLegObstacleContactEvents;
        public int frontLegTopContactEvents;
        public int middleLegTopContactEvents;
        public int rearLegTopContactEvents;
        public float frontLegObstacleContactSeconds;
        public float middleLegObstacleContactSeconds;
        public float rearLegObstacleContactSeconds;
        public int brainFrameCount;
        public int staleEvents;
        public FlyMetricStatistic DNp09_Hz;
        public FlyMetricStatistic DNa02_R_Hz;
        public FlyMetricStatistic DNa02_L_Hz;
        public FlyMetricStatistic decodedForward;
        public FlyMetricStatistic decodedTurn;
    }

    public sealed class FlyStepObstacleCharacterization : MonoBehaviour
    {
        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyLocomotionController controller;
        [SerializeField] private MockMotorSource mockSource;
        [SerializeField] private BrainMotorSource brainSource;
        [SerializeField] private BrainTcpClient brainClient;
        [SerializeField] private ReplayMotorSource replaySource;
        [SerializeField] private FlyStepObstacle obstacle;
        [SerializeField] private FlyLocalReflexLayer reflexLayer;
        [SerializeField] private FlyStepKinematicsDiagnostics kinematicsDiagnostics;
        [SerializeField] private float defaultTrialDurationSeconds = 25f;
        [SerializeField] private float brainConnectionTimeoutSeconds = 30f;
        [SerializeField] private float successHoldSeconds = 0.75f;
        [SerializeField] private float fallHeight = 0.35f;
        [SerializeField] private float stallVelocityThresholdMps = 0.02f;

        private readonly List<float> dNp09Samples = new List<float>();
        private readonly List<float> dNa02RSamples = new List<float>();
        private readonly List<float> dNa02LSamples = new List<float>();
        private readonly List<float> forwardSamples = new List<float>();
        private readonly List<float> turnSamples = new List<float>();
        private readonly List<float> rawForwardSamples = new List<float>();
        private readonly List<float> effectiveForwardSamples = new List<float>();
        private readonly List<float> yawRateSamples = new List<float>();

        private string outputPath;
        private string action = "FORWARD";
        private int trialId;
        private float trialDurationSeconds;
        private float waitStartedAt;
        private float trialStartedAt;
        private float firstContactAt = -1f;
        private float successCandidateAt = -1f;
        private Vector3 rootStartPosition;
        private float maxAbsPitch;
        private float maxAbsRoll;
        private float approachVelocity;
        private float stalledSeconds;
        private float startYaw;
        private bool useBrain;
        private bool useReplay;
        private bool actionSent;
        private bool trialStarted;
        private bool finished;
        private bool seenBrainFrame;
        private bool previousFrameWasStale;
        private int staleEvents;
        private int lastBrainFrame = -1;
        private int brainFrameCount;
        private bool fallDetected;
        private float initialPhaseDegrees;
        private float firstObstacleContactPhaseDegrees = -1f;
        private string frameRecordPath;
        private StreamWriter frameWriter;
        private int recordedFrameCount;
        private bool reflexEnabled;
        private string reflexMode = "NONE";
        private bool adhesionEnabled;
        private float adhesionNormalStrength;
        private float adhesionShearStrength;
        private float adhesionAttachDelay;
        private float adhesionDetachThreshold;
        private float peakTotalGripUtilization;

        public void Configure(FlyBody body, FlyLocomotionController locomotionController, MockMotorSource mock, BrainMotorSource brain, BrainTcpClient client, ReplayMotorSource replay, FlyStepObstacle step, FlyLocalReflexLayer reflex, FlyStepKinematicsDiagnostics kinematics = null)
        {
            flyBody = body;
            controller = locomotionController;
            mockSource = mock;
            brainSource = brain;
            brainClient = client;
            replaySource = replay;
            obstacle = step;
            reflexLayer = reflex;
            kinematicsDiagnostics = kinematics;
        }

        private void Start()
        {
            if (!HasCommandLineFlag("-flyStepCharacterize"))
            {
                enabled = false;
                return;
            }

            action = GetCommandLineValue("-flyStepAction");
            if (string.IsNullOrEmpty(action))
            {
                action = "FORWARD";
            }

            trialId = ParseIntArgument("-flyStepTrialId", 1);
            trialDurationSeconds = Mathf.Max(5f, ParseFloatArgument("-flyStepTrialDurationSeconds", defaultTrialDurationSeconds));
            initialPhaseDegrees = ParseFloatArgument("-flyStepInitialPhaseDegrees", 0f);
            reflexEnabled = HasCommandLineFlag("-flyStepEnableReflex");
            reflexMode = reflexEnabled ? GetCommandLineValue("-flyStepReflexMode") : "NONE";
            if (string.IsNullOrEmpty(reflexMode))
            {
                reflexMode = "BOTH";
            }

            if (reflexLayer != null)
            {
                reflexLayer.ResetState();
                reflexLayer.ConfigureMode(reflexEnabled ? reflexMode : "NONE");
                reflexLayer.enabled = reflexEnabled;
            }

            adhesionEnabled = HasCommandLineFlag("-flyStepEnableAdhesion");
            adhesionNormalStrength = ParseFloatArgument("-flyAdhesionNormalStrength", 0.35f);
            adhesionShearStrength = ParseFloatArgument("-flyAdhesionShearStrength", 0.20f);
            adhesionAttachDelay = ParseFloatArgument("-flyAdhesionAttachDelay", 0.02f);
            adhesionDetachThreshold = ParseFloatArgument("-flyAdhesionDetachThreshold", 1.25f);
            controller.ConfigureFootAdhesion(adhesionEnabled, adhesionNormalStrength, adhesionShearStrength,
                                             adhesionAttachDelay, adhesionDetachThreshold);

            controller.SetPhaseForDiagnostics(initialPhaseDegrees * Mathf.Deg2Rad);
            outputPath = GetCommandLineValue("-flyStepOutput");
            if (string.IsNullOrEmpty(outputPath))
            {
                outputPath = Path.Combine(Directory.GetCurrentDirectory(), "Logs", "fly-step-trial.json");
            }

            useBrain = HasCommandLineFlag("-flyStepUseBrain");
            frameRecordPath = GetCommandLineValue("-flyStepRecordBrainFrames");
            string replayPath = GetCommandLineValue("-flyStepReplayFile");
            useReplay = !string.IsNullOrEmpty(replayPath);
            if (useReplay)
            {
                replaySource.Configure(replayPath);
                controller.SetMotorSource(replaySource);
                if (replaySource.FrameCount == 0)
                {
                    Finish(false, true, "UNKNOWN");
                    return;
                }

                StartTrial();
                return;
            }

            waitStartedAt = Time.unscaledTime;
            if (useBrain)
            {
                brainClient.enabled = true;
                brainSource.enabled = true;
                controller.SetMotorSource(brainSource);
                OpenFrameRecorder();
                brainClient.Connect();
                Debug.Log("FLY_STEP_TRIAL_WAIT source=BrainFrame height=" + obstacle.ObstacleHeight.ToString("0.###", CultureInfo.InvariantCulture));
            }
            else
            {
                controller.SetMotorSource(mockSource);
                StartTrial();
            }
        }

        private void Update()
        {
            if (!enabled || finished || !trialStarted)
            {
                return;
            }

            if (Time.unscaledTime - trialStartedAt >= trialDurationSeconds)
            {
                Finish(false, true, ClassifyFailure());
            }
        }

        private void FixedUpdate()
        {
            if (!enabled || finished)
            {
                return;
            }

            if (!trialStarted)
            {
                if (useBrain && brainClient.ConnectionState == "CONNECTED" && !actionSent)
                {
                    brainClient.SetAction(action);
                    actionSent = true;
                    StartTrial();
                }
                else if (useBrain && Time.unscaledTime - waitStartedAt > brainConnectionTimeoutSeconds)
                {
                    Finish(false, true, "G_TIMEOUT_STALL");
                }

                return;
            }

            CollectSample();
            EvaluateTrialState();
        }

        private void StartTrial()
        {
            trialStarted = true;
            trialStartedAt = Time.unscaledTime;
            rootStartPosition = flyBody.Position;
            startYaw = flyBody.transform.eulerAngles.y;
            if (kinematicsDiagnostics != null)
            {
                kinematicsDiagnostics.BeginTrial(trialId, useBrain ? "BrainFrame" : useReplay ? "BrainFrameReplay" : "MockMotorSource", mockSource == null ? 0f : mockSource.Forward);
            }
            Debug.Log("FLY_STEP_TRIAL_START trial=" + trialId + " source=" + (useBrain ? "BrainFrame" : "MockMotorSource") + " height=" + obstacle.ObstacleHeight.ToString("0.###", CultureInfo.InvariantCulture));
        }

        private void CollectSample()
        {
            Vector3 position = flyBody.Position;
            Vector3 velocity = flyBody.LinearVelocity;
            Vector3 angles = GetSignedEulerAngles(flyBody.transform.eulerAngles);
            FlyMotorCommand motor = controller.CurrentMotor;
            FlyMotorCommand rawMotor = reflexLayer == null || !reflexLayer.enabled
                ? motor
                : reflexLayer.RawMotor;
            FlyMotorCommand effectiveMotor = reflexLayer == null || !reflexLayer.enabled
                ? motor
                : reflexLayer.EffectiveMotor;
            BrainFrame frame = useBrain
                ? brainSource.LatestFrame
                : useReplay ? replaySource.LatestFrame : null;

            if (frame != null && frame.sequence != lastBrainFrame)
            {
                lastBrainFrame = frame.sequence;
                brainFrameCount++;
                seenBrainFrame = true;
                if (useBrain)
                {
                    RecordFrame(frame);
                }
            }

            if (useBrain)
            {
                bool frameIsStale = seenBrainFrame && !brainSource.HasFreshFrame;
                if (frameIsStale && !previousFrameWasStale)
                {
                    staleEvents++;
                }

                previousFrameWasStale = frameIsStale;
            }

            dNp09Samples.Add(frame == null || frame.brain == null ? 0f : frame.brain.DNp09_Hz);
            dNa02RSamples.Add(frame == null || frame.brain == null ? 0f : frame.brain.DNa02_R_Hz);
            dNa02LSamples.Add(frame == null || frame.brain == null ? 0f : frame.brain.DNa02_L_Hz);
            forwardSamples.Add(motor.forward);
            turnSamples.Add(motor.turn);
            rawForwardSamples.Add(rawMotor.forward);
            effectiveForwardSamples.Add(effectiveMotor.forward);
            yawRateSamples.Add(flyBody.AngularVelocity.y * Mathf.Rad2Deg);
            float totalGrip = 0f;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null && adhesion.Attached)
                {
                    totalGrip += adhesion.GripUtilization;
                }
            }
            peakTotalGripUtilization = Mathf.Max(peakTotalGripUtilization, totalGrip);
            maxAbsPitch = Mathf.Max(maxAbsPitch, Mathf.Abs(angles.x));
            maxAbsRoll = Mathf.Max(maxAbsRoll, Mathf.Abs(angles.z));

            if (position.y < fallHeight || Mathf.Abs(angles.x) > 80f || Mathf.Abs(angles.z) > 80f)
            {
                fallDetected = true;
            }

            if (firstContactAt < 0f && (obstacle.FrontContactEvents > 0 || obstacle.TopContactEvents > 0))
            {
                firstContactAt = Time.unscaledTime;
                approachVelocity = velocity.x;
                firstObstacleContactPhaseDegrees = controller.Phase * Mathf.Rad2Deg;
            }

            if (firstContactAt >= 0f && !IsSuccessPose(position))
            {
                if (Mathf.Abs(velocity.x) < stallVelocityThresholdMps)
                {
                    stalledSeconds += Time.fixedDeltaTime;
                }
            }
        }

        private void EvaluateTrialState()
        {
            if (fallDetected)
            {
                Finish(false, false, "F_COMPLETE_FALL");
                return;
            }

            if (IsSuccessPose(flyBody.Position))
            {
                if (successCandidateAt < 0f)
                {
                    successCandidateAt = Time.unscaledTime;
                }
                else if (Time.unscaledTime - successCandidateAt >= successHoldSeconds)
                {
                    Finish(true, false, "SUCCESS");
                }
            }
            else
            {
                successCandidateAt = -1f;
            }
        }

        private bool IsSuccessPose(Vector3 position)
        {
            float requiredX = obstacle.UpperPlatformStartX + 0.45f;
            float requiredY = obstacle.ObstacleHeight + 0.45f;
            return position.x >= requiredX && position.y >= requiredY && flyBody.GroundContactCount > 0;
        }

        private void Finish(bool success, bool timeout, string failureMode)
        {
            if (finished)
            {
                return;
            }

            finished = true;
            if (kinematicsDiagnostics != null)
            {
                kinematicsDiagnostics.EndTrial();
            }
            Vector3 finalPosition = flyBody.Position;
            Vector3 finalVelocity = flyBody.LinearVelocity;
            Vector3 finalAngles = GetSignedEulerAngles(flyBody.transform.eulerAngles);
            float now = Time.unscaledTime;
            float totalSeconds = trialStarted ? now - trialStartedAt : 0f;
            float timeToContact = firstContactAt < 0f ? -1f : firstContactAt - trialStartedAt;
            float timeToClear = success && firstContactAt >= 0f ? now - firstContactAt : -1f;

            var result = new FlyStepObstacleTrialResult
            {
                trialId = trialId,
                source = useBrain ? "BrainFrame" : useReplay ? "BrainFrameReplay" : "MockMotorSource",
                action = action,
                frameRecordPath = frameRecordPath,
                recordedFrameCount = recordedFrameCount,
                mockForward = mockSource == null ? 0f : mockSource.Forward,
                initialPhaseDegrees = initialPhaseDegrees,
                firstObstacleContactPhaseDegrees = firstObstacleContactPhaseDegrees,
                obstacleHeight = obstacle.ObstacleHeight,
                success = success,
                failureMode = success ? "SUCCESS" : failureMode,
                timeToContactSeconds = timeToContact,
                timeToClearSeconds = timeToClear,
                totalTrialSeconds = totalSeconds,
                rootStartPosition = rootStartPosition,
                rootFinalPosition = finalPosition,
                finalRootVelocity = finalVelocity,
                worldDisplacementMeters = Vector3.Distance(finalPosition, rootStartPosition),
                forwardDisplacementMeters = finalPosition.x - rootStartPosition.x,
                averageForwardVelocityMps = totalSeconds <= 0f ? 0f : (finalPosition.x - rootStartPosition.x) / totalSeconds,
                averageYawRateDegreesPerSecond = BuildStatistic(yawRateSamples).mean,
                approachVelocityMps = approachVelocity,
                finalPitchDegrees = finalAngles.x,
                finalRollDegrees = finalAngles.z,
                finalYawDegrees = Mathf.DeltaAngle(startYaw, flyBody.transform.eulerAngles.y),
                maxAbsPitchDegrees = maxAbsPitch,
                maxAbsRollDegrees = maxAbsRoll,
                stalledSeconds = stalledSeconds,
                fallDetected = fallDetected,
                timeout = timeout,
                reflexEnabled = reflexEnabled,
                reflexMode = reflexMode,
                adhesionEnabled = adhesionEnabled,
                adhesionNormalStrength = adhesionNormalStrength,
                adhesionShearStrength = adhesionShearStrength,
                adhesionAttachDelay = adhesionAttachDelay,
                adhesionDetachThreshold = adhesionDetachThreshold,
                adhesionAttachmentCount = GetAdhesionAttachmentCount(),
                adhesionDetachCount = GetAdhesionDetachCount(),
                adhesionContactTickCount = GetAdhesionContactTickCount(),
                adhesionStanceTickCount = GetAdhesionStanceTickCount(),
                attachedFeetAtFinish = GetAttachedFootCount(),
                peakTotalGripUtilization = peakTotalGripUtilization,
                footAdhesionDiagnostics = BuildFootAdhesionDiagnostics(),
                articulationDofCount = GetArticulationDofCount(),
                rawForward = BuildStatistic(rawForwardSamples),
                effectiveForward = BuildStatistic(effectiveForwardSamples),
                phaseEscapeActivationCount = reflexLayer == null ? 0 : reflexLayer.PhaseEscapeActivationCount,
                phaseEscapeActivationTimeSeconds = GetRelativeActivationTime(reflexLayer == null ? -1f : reflexLayer.LastPhaseEscapeActivationTime),
                phaseEscapeOffsetAppliedDegrees = reflexLayer == null ? 0f : reflexLayer.PhaseEscapeOffsetAppliedDegrees,
                phaseEscapePhaseBeforeDegrees = reflexLayer == null ? -1f : reflexLayer.PhaseEscapePhaseBeforeDegrees,
                phaseEscapePhaseAfterDegrees = reflexLayer == null ? -1f : reflexLayer.PhaseEscapePhaseAfterDegrees,
                propulsionAssistActivationCount = reflexLayer == null ? 0 : reflexLayer.PropulsionAssistActivationCount,
                propulsionAssistActivationTimeSeconds = GetRelativeActivationTime(reflexLayer == null ? -1f : reflexLayer.LastPropulsionAssistActivationTime),
                propulsionAssistDurationSeconds = reflexLayer == null ? 0f : reflexLayer.PropulsionAssistDurationSeconds,
                propulsionAssistActiveAtFinish = reflexLayer != null && reflexLayer.PropulsionAssistActive,
                rearStepUpActivationCount = reflexLayer == null ? 0 : reflexLayer.RearStepUpActivationCount,
                rearStepUpActivationTimeSeconds = GetRelativeActivationTime(reflexLayer == null ? -1f : reflexLayer.LastRearStepUpActivationTime),
                rearStepUpState = reflexLayer == null ? "NONE" : reflexLayer.RearStepUpStateName,
                activeRearLeg = reflexLayer == null ? string.Empty : reflexLayer.ActiveRearLegId,
                rearStepUpCoxaOffsetAppliedDegrees = reflexLayer == null ? 0f : reflexLayer.RearStepUpCoxaOffsetAppliedDegrees,
                rearStepUpFemurOffsetAppliedDegrees = reflexLayer == null ? 0f : reflexLayer.RearStepUpFemurOffsetAppliedDegrees,
                rearStepUpTibiaOffsetAppliedDegrees = reflexLayer == null ? 0f : reflexLayer.RearStepUpTibiaOffsetAppliedDegrees,
                rearStepUpBlend = reflexLayer == null ? 0f : reflexLayer.RearStepUpBlend,
                rearSupportPresentAtFinish = reflexLayer != null && reflexLayer.RearSupportPresent,
                frontObstacleContactEvents = obstacle.FrontContactEvents,
                topObstacleContactEvents = obstacle.TopContactEvents,
                frontObstacleContactSeconds = obstacle.FrontContactSeconds,
                topObstacleContactSeconds = obstacle.TopContactSeconds,
                frontLegObstacleContactEvents = obstacle.GetFrontLegEvents("F"),
                middleLegObstacleContactEvents = obstacle.GetFrontLegEvents("M"),
                rearLegObstacleContactEvents = obstacle.GetFrontLegEvents("H"),
                frontLegTopContactEvents = obstacle.GetTopLegEvents("F"),
                middleLegTopContactEvents = obstacle.GetTopLegEvents("M"),
                rearLegTopContactEvents = obstacle.GetTopLegEvents("H"),
                frontLegObstacleContactSeconds = obstacle.GetFrontLegSeconds("F"),
                middleLegObstacleContactSeconds = obstacle.GetFrontLegSeconds("M"),
                rearLegObstacleContactSeconds = obstacle.GetFrontLegSeconds("H"),
                brainFrameCount = brainFrameCount,
                staleEvents = staleEvents,
                DNp09_Hz = BuildStatistic(dNp09Samples),
                DNa02_R_Hz = BuildStatistic(dNa02RSamples),
                DNa02_L_Hz = BuildStatistic(dNa02LSamples),
                decodedForward = BuildStatistic(forwardSamples),
                decodedTurn = BuildStatistic(turnSamples)
            };

            WriteResult(result);
            CloseFrameRecorder();
            Debug.Log("FLY_STEP_TRIAL_DONE trial=" + trialId + " height=" + obstacle.ObstacleHeight.ToString("0.###", CultureInfo.InvariantCulture) + " success=" + success + " failureMode=" + result.failureMode);
            Application.Quit(0);
        }

        private float GetRelativeActivationTime(float activationTime)
        {
            return activationTime < 0f || !trialStarted
                ? -1f
                : Mathf.Max(0f, activationTime - trialStartedAt);
        }

        private int GetAdhesionAttachmentCount()
        {
            int count = 0;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null) count += adhesion.AttachmentCount;
            }
            return count;
        }

        private int GetAdhesionDetachCount()
        {
            int count = 0;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null) count += adhesion.DetachCount;
            }
            return count;
        }

        private int GetAttachedFootCount()
        {
            int count = 0;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null && adhesion.Attached) count++;
            }
            return count;
        }

        private int GetAdhesionContactTickCount()
        {
            int count = 0;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null) count += adhesion.ContactTickCount;
            }
            return count;
        }

        private int GetAdhesionStanceTickCount()
        {
            int count = 0;
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyFootAdhesion adhesion = flyBody.Legs[i] == null ? null : flyBody.Legs[i].FootAdhesion;
                if (adhesion != null) count += adhesion.StanceTickCount;
            }
            return count;
        }

        private FlyFootAdhesionDiagnostic[] BuildFootAdhesionDiagnostics()
        {
            var diagnostics = new FlyFootAdhesionDiagnostic[flyBody.Legs.Count];
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyLeg leg = flyBody.Legs[i];
                FlyFootContact contact = leg == null ? null : leg.FootContact;
                FlyFootAdhesion adhesion = leg == null ? null : leg.FootAdhesion;
                diagnostics[i] = new FlyFootAdhesionDiagnostic
                {
                    legId = leg == null ? string.Empty : leg.LegId,
                    footColliderEntityId = contact == null ? string.Empty : contact.FootColliderEntityId,
                    attachedArticulationBodyMatches = contact != null && contact.AttachedArticulationBodyMatches,
                    otherCollider = contact == null ? string.Empty : contact.OtherColliderName,
                    contactEnterCount = contact == null ? 0 : contact.EnterCount,
                    contactStayCount = contact == null ? 0 : contact.StayCount,
                    contactExitCount = contact == null ? 0 : contact.ExitCount,
                    stanceTicks = adhesion == null ? 0 : adhesion.StanceTickCount,
                    contactTicks = adhesion == null ? 0 : adhesion.ContactTickCount,
                    stanceContactTicks = adhesion == null ? 0 : adhesion.EligibleTickCount,
                    attachCount = adhesion == null ? 0 : adhesion.AttachmentCount,
                    detachCount = adhesion == null ? 0 : adhesion.DetachCount,
                    detachSwingCount = adhesion == null ? 0 : adhesion.SwingDetachCount,
                    detachContactLostCount = adhesion == null ? 0 : adhesion.ContactLostDetachCount,
                    detachShearOverloadCount = adhesion == null ? 0 : adhesion.ShearOverloadDetachCount,
                    meanAttachmentDurationSeconds = adhesion == null ? 0f : adhesion.MeanAttachmentDuration,
                    maxAttachmentDurationSeconds = adhesion == null ? 0f : adhesion.MaxAttachmentDuration,
                    normalAdhesionImpulseNs = adhesion == null ? 0f : adhesion.AccumulatedNormalImpulse,
                    shearAdhesionImpulseNs = adhesion == null ? 0f : adhesion.AccumulatedShearImpulse,
                    peakNormalUtilization = adhesion == null ? 0f : adhesion.PeakNormalUtilization,
                    peakShearUtilization = adhesion == null ? 0f : adhesion.PeakShearUtilization,
                    peakGripUtilization = adhesion == null ? 0f : adhesion.PeakGripUtilization,
                    meanContactLostStanceProgress = adhesion == null ? -1f : adhesion.MeanContactLostStanceProgress,
                    normalForceDot = adhesion == null ? 1f : adhesion.LastNormalForceDot
                };
            }
            return diagnostics;
        }

        private int GetArticulationDofCount()
        {
            int count = 0;
            ArticulationBody[] bodies = flyBody.GetComponentsInChildren<ArticulationBody>();
            for (int i = 0; i < bodies.Length; i++) count += bodies[i].dofCount;
            return count;
        }

        private void OpenFrameRecorder()
        {
            if (string.IsNullOrEmpty(frameRecordPath))
            {
                return;
            }

            string directory = Path.GetDirectoryName(frameRecordPath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            frameWriter = new StreamWriter(frameRecordPath, false);
        }

        private void RecordFrame(BrainFrame frame)
        {
            if (frameWriter == null || frame == null)
            {
                return;
            }

            frameWriter.WriteLine(JsonUtility.ToJson(frame));
            frameWriter.Flush();
            recordedFrameCount++;
        }

        private void CloseFrameRecorder()
        {
            if (frameWriter == null)
            {
                return;
            }

            frameWriter.Flush();
            frameWriter.Dispose();
            frameWriter = null;
        }

        private string ClassifyFailure()
        {
            if (fallDetected)
            {
                return "F_COMPLETE_FALL";
            }

            if (obstacle.FrontContactEvents == 0)
            {
                // No front-face contact plus loss of forward progress is kept
                // separate from a genuine timeout with no displacement.
                if (flyBody.Position.x < rootStartPosition.x + 0.5f)
                {
                    return "E_SLIPPING";
                }

                if (obstacle.TopContactEvents > 0 && stalledSeconds < 1f)
                {
                    return "UNKNOWN";
                }

                return "G_TIMEOUT_STALL";
            }

            if (maxAbsPitch > 30f || maxAbsRoll > 30f)
            {
                return "D_BODY_PITCH_ROLL_INSTABILITY";
            }

            if (obstacle.FrontContactEvents > 0 && obstacle.TopContactEvents == 0 && stalledSeconds >= 0.5f)
            {
                return "A_FRONT_LEG_STUMBLE";
            }

            if (obstacle.TopContactEvents > 0 && flyBody.Position.y < obstacle.ObstacleHeight + 0.45f)
            {
                return "B_FRONT_TOP_BODY_CANNOT_RISE";
            }

            if (obstacle.TopContactEvents > 0 && obstacle.GetTopLegEvents("H") == 0)
            {
                return "C_REAR_LEG_FOLLOW_FAILURE";
            }

            if (stalledSeconds >= 1f)
            {
                return "G_TIMEOUT_STALL";
            }

            return "UNKNOWN";
        }

        private void WriteResult(FlyStepObstacleTrialResult result)
        {
            string directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            File.WriteAllText(outputPath, JsonUtility.ToJson(result, true) + Environment.NewLine);
        }

        private static FlyMetricStatistic BuildStatistic(List<float> samples)
        {
            if (samples.Count == 0)
            {
                return new FlyMetricStatistic();
            }

            float min = samples[0];
            float max = samples[0];
            double sum = 0.0;
            for (int i = 0; i < samples.Count; i++)
            {
                min = Mathf.Min(min, samples[i]);
                max = Mathf.Max(max, samples[i]);
                sum += samples[i];
            }

            return new FlyMetricStatistic
            {
                mean = (float)(sum / samples.Count),
                min = min,
                max = max
            };
        }

        private static Vector3 GetSignedEulerAngles(Vector3 eulerAngles)
        {
            return new Vector3(
                Mathf.DeltaAngle(0f, eulerAngles.x),
                Mathf.DeltaAngle(0f, eulerAngles.y),
                Mathf.DeltaAngle(0f, eulerAngles.z));
        }

        private static bool HasCommandLineFlag(string name)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length; i++)
            {
                if (arguments[i] == name)
                {
                    return true;
                }
            }

            return false;
        }

        private static string GetCommandLineValue(string name)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name)
                {
                    return arguments[i + 1];
                }
            }

            return string.Empty;
        }

        private static float ParseFloatArgument(string name, float fallback)
        {
            string value = GetCommandLineValue(name);
            return float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out float parsed)
                ? parsed
                : fallback;
        }

        private static int ParseIntArgument(string name, int fallback)
        {
            string value = GetCommandLineValue(name);
            return int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed)
                ? parsed
                : fallback;
        }
    }
}
