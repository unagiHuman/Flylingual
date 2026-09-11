using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using FlyBrainPoC;
using UnityEngine;

namespace FlyLocomotionPoC
{
    [Serializable]
    public sealed class FlyMetricStatistic
    {
        public float mean;
        public float min;
        public float max;
    }

    [Serializable]
    public sealed class FlyActionCharacterizationResult
    {
        public int protocolVersion = 1;
        public string action;
        public bool completed;
        public string error;
        public float settlingSeconds;
        public float durationSeconds;
        public int sampleCount;
        public Vector3 startPosition;
        public Vector3 endPosition;
        public float forwardDisplacementMeters;
        public float worldDisplacementMeters;
        public float yawDeltaDegrees;
        public float minRootY;
        public int fallCount;
        public int staleEvents;
        public FlyMetricStatistic forwardVelocity;
        public FlyMetricStatistic yawRate;
        public FlyMetricStatistic motorForward;
        public FlyMetricStatistic motorTurn;
        public FlyMetricStatistic DNp09_Hz;
        public FlyMetricStatistic DNa02_R_Hz;
        public FlyMetricStatistic DNa02_L_Hz;
        public int firstBrainFrame;
        public int lastBrainFrame;
    }

    public sealed class FlyActionCharacterization : MonoBehaviour
    {
        private static readonly string[] AllowedActions =
        {
            "STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L"
        };

        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyLocomotionController controller;
        [SerializeField] private BrainMotorSource brainSource;
        [SerializeField] private BrainTcpClient brainClient;
        [SerializeField] private float defaultDurationSeconds = 10f;
        [SerializeField] private float settlingSeconds = 2f;
        [SerializeField] private float connectionTimeoutSeconds = 30f;
        [SerializeField] private float fallHeight = 0.35f;

        private readonly List<float> forwardVelocitySamples = new List<float>();
        private readonly List<float> yawRateSamples = new List<float>();
        private readonly List<float> motorForwardSamples = new List<float>();
        private readonly List<float> motorTurnSamples = new List<float>();
        private readonly List<float> dNp09Samples = new List<float>();
        private readonly List<float> dNa02RSamples = new List<float>();
        private readonly List<float> dNa02LSamples = new List<float>();

        private string action;
        private string outputPath;
        private float durationSeconds;
        private float waitStartedAt;
        private float actionStartedAt;
        private float measurementStartedAt;
        private Vector3 startPosition;
        private Vector3 startForward;
        private float startYaw;
        private float minRootY;
        private int fallCount;
        private int staleEvents;
        private int firstBrainFrame = -1;
        private int lastBrainFrame = -1;
        private bool previousFrameWasStale;
        private bool actionSent;
        private bool measurementStarted;
        private bool seenBrainFrame;
        private bool finished;

        public void Configure(FlyBody body, FlyLocomotionController locomotionController, BrainMotorSource source, BrainTcpClient client)
        {
            flyBody = body;
            controller = locomotionController;
            brainSource = source;
            brainClient = client;
        }

        private void Start()
        {
            if (!HasCommandLineFlag("-flyCharacterize"))
            {
                enabled = false;
                return;
            }

            action = GetCommandLineValue("-flyCharacterizationAction");
            outputPath = GetCommandLineValue("-flyCharacterizationOutput");
            if (string.IsNullOrEmpty(outputPath))
            {
                outputPath = Path.Combine(Directory.GetCurrentDirectory(), "Logs", "fly-action-" + action + ".json");
            }

            if (!IsAllowedAction(action))
            {
                FinishWithError("Unknown characterization action: " + action);
                return;
            }

            durationSeconds = ParseFloatArgument("-flyCharacterizationDurationSeconds", defaultDurationSeconds);
            durationSeconds = Mathf.Max(1f, durationSeconds);

            waitStartedAt = Time.unscaledTime;
            brainClient.enabled = true;
            brainSource.enabled = true;
            brainClient.Connect();
            controller.SetMotorSource(brainSource);
            Debug.Log("FLY_CHARACTERIZATION_WAIT action=" + action);
        }

        private void Update()
        {
            if (!enabled || finished || !measurementStarted)
            {
                return;
            }

            if (Time.unscaledTime - measurementStartedAt >= durationSeconds)
            {
                FinishSuccessfully();
            }
        }

        private void FixedUpdate()
        {
            if (!enabled || finished)
            {
                return;
            }

            if (!measurementStarted)
            {
                if (brainClient != null && brainClient.ConnectionState == "CONNECTED" && !actionSent)
                {
                    brainClient.SetAction(action);
                    actionSent = true;
                    actionStartedAt = Time.unscaledTime;
                    Debug.Log("FLY_CHARACTERIZATION_ACTION_SENT action=" + action + " settleSeconds=" + settlingSeconds.ToString("0.###", CultureInfo.InvariantCulture));
                }
                else if (actionSent && Time.unscaledTime - actionStartedAt >= settlingSeconds)
                {
                    measurementStarted = true;
                    measurementStartedAt = Time.unscaledTime;
                    startPosition = flyBody.Position;
                    startForward = flyBody.transform.forward;
                    startYaw = flyBody.transform.eulerAngles.y;
                    minRootY = startPosition.y;
                    Debug.Log("FLY_CHARACTERIZATION_START action=" + action + " durationSeconds=" + durationSeconds.ToString("0.###", CultureInfo.InvariantCulture));
                }
                else if (Time.unscaledTime - waitStartedAt > connectionTimeoutSeconds)
                {
                    FinishWithError("Brain Server connection timeout: " + (brainClient == null ? "null" : brainClient.LastError));
                }

                return;
            }

            CollectSample();
        }

        private void CollectSample()
        {
            Vector3 position = flyBody.Position;
            Vector3 velocity = flyBody.LinearVelocity;
            Vector3 angularVelocity = flyBody.AngularVelocity;
            FlyMotorCommand motor = controller.CurrentMotor;
            BrainFrame frame = brainSource.LatestFrame;

            int frameSequence = frame == null ? -1 : frame.sequence;
            if (frameSequence >= 0)
            {
                seenBrainFrame = true;
                if (firstBrainFrame < 0)
                {
                    firstBrainFrame = frameSequence;
                }

                lastBrainFrame = frameSequence;
            }

            forwardVelocitySamples.Add(Vector3.Dot(velocity, startForward));
            yawRateSamples.Add(angularVelocity.y);
            motorForwardSamples.Add(motor.forward);
            motorTurnSamples.Add(motor.turn);
            dNp09Samples.Add(frame == null || frame.brain == null ? 0f : frame.brain.DNp09_Hz);
            dNa02RSamples.Add(frame == null || frame.brain == null ? 0f : frame.brain.DNa02_R_Hz);
            dNa02LSamples.Add(frame == null || frame.brain == null ? 0f : frame.brain.DNa02_L_Hz);

            minRootY = Mathf.Min(minRootY, position.y);
            if (position.y < fallHeight)
            {
                fallCount++;
            }

            bool frameIsStale = seenBrainFrame && !brainSource.HasFreshFrame;
            if (frameIsStale && !previousFrameWasStale)
            {
                staleEvents++;
            }

            previousFrameWasStale = frameIsStale;
        }

        private void FinishSuccessfully()
        {
            if (finished)
            {
                return;
            }

            finished = true;
            Vector3 endPosition = flyBody.Position;
            FlyActionCharacterizationResult result = new FlyActionCharacterizationResult
            {
                action = action,
                completed = true,
                durationSeconds = Time.unscaledTime - measurementStartedAt,
                settlingSeconds = settlingSeconds,
                sampleCount = forwardVelocitySamples.Count,
                startPosition = startPosition,
                endPosition = endPosition,
                forwardDisplacementMeters = Vector3.Dot(endPosition - startPosition, startForward),
                worldDisplacementMeters = Vector3.Distance(endPosition, startPosition),
                yawDeltaDegrees = Mathf.DeltaAngle(startYaw, flyBody.transform.eulerAngles.y),
                minRootY = minRootY,
                fallCount = fallCount,
                staleEvents = staleEvents,
                forwardVelocity = BuildStatistic(forwardVelocitySamples),
                yawRate = BuildStatistic(yawRateSamples),
                motorForward = BuildStatistic(motorForwardSamples),
                motorTurn = BuildStatistic(motorTurnSamples),
                DNp09_Hz = BuildStatistic(dNp09Samples),
                DNa02_R_Hz = BuildStatistic(dNa02RSamples),
                DNa02_L_Hz = BuildStatistic(dNa02LSamples),
                firstBrainFrame = firstBrainFrame,
                lastBrainFrame = lastBrainFrame
            };

            WriteResult(result);
            Debug.Log("FLY_CHARACTERIZATION_DONE action=" + action + " forwardDisplacement=" + result.forwardDisplacementMeters.ToString("0.###", CultureInfo.InvariantCulture) + " yawDelta=" + result.yawDeltaDegrees.ToString("0.###", CultureInfo.InvariantCulture));
            Application.Quit(0);
        }

        private void FinishWithError(string message)
        {
            if (finished)
            {
                return;
            }

            finished = true;
            var result = new FlyActionCharacterizationResult
            {
                action = action,
                completed = false,
                error = message,
                durationSeconds = 0f,
                sampleCount = 0,
                firstBrainFrame = -1,
                lastBrainFrame = -1
            };
            WriteResult(result);
            Debug.LogError("FLY_CHARACTERIZATION_ERROR " + message);
            Application.Quit(1);
        }

        private void WriteResult(FlyActionCharacterizationResult result)
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

        private static bool IsAllowedAction(string value)
        {
            for (int i = 0; i < AllowedActions.Length; i++)
            {
                if (AllowedActions[i] == value)
                {
                    return true;
                }
            }

            return false;
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
    }
}
