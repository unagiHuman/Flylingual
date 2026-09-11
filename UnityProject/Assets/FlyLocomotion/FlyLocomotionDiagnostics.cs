using System.Globalization;
using FlyBrainPoC;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyLocomotionDiagnostics : MonoBehaviour
    {
        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyLocomotionController controller;
        [SerializeField] private MockMotorSource mockSource;
        [SerializeField] private BrainMotorSource brainSource;
        [SerializeField] private BrainTcpClient brainClient;
        [SerializeField] private float statusLogIntervalSeconds = 1f;

        private float nextStatusLogTime;
        private string pendingBrainAction;
        private bool brainActionSent;

        private void Start()
        {
            if (HasCommandLineFlag("-flyUseBrain"))
            {
                ActivateBrainSource();
                pendingBrainAction = GetCommandLineValue("-flyBrainAction");
            }
        }

        public void Configure(FlyBody body, FlyLocomotionController locomotionController, MockMotorSource mock, BrainMotorSource brain, BrainTcpClient client, float logInterval)
        {
            flyBody = body;
            controller = locomotionController;
            mockSource = mock;
            brainSource = brain;
            brainClient = client;
            statusLogIntervalSeconds = Mathf.Max(0.1f, logInterval);
        }

        private void Update()
        {
            if (!brainActionSent && !string.IsNullOrEmpty(pendingBrainAction) &&
                brainClient != null && brainClient.ConnectionState == "CONNECTED")
            {
                brainClient.SetAction(pendingBrainAction);
                brainActionSent = true;
            }

            if (Time.time >= nextStatusLogTime)
            {
                nextStatusLogTime = Time.time + statusLogIntervalSeconds;
                LogStatus();
            }
        }

        private void LogStatus()
        {
            if (flyBody == null || controller == null)
            {
                return;
            }

            FlyMotorCommand motor = controller.CurrentMotor;
            Vector3 velocity = flyBody.LinearVelocity;
            Vector3 angularVelocity = flyBody.AngularVelocity;
            BrainFrame brainFrame = brainSource == null ? null : brainSource.LatestFrame;
            int frameSequence = brainFrame == null ? -1 : brainFrame.sequence;
            float dNp09 = brainFrame == null || brainFrame.brain == null ? 0f : brainFrame.brain.DNp09_Hz;
            float dNa02R = brainFrame == null || brainFrame.brain == null ? 0f : brainFrame.brain.DNa02_R_Hz;
            float dNa02L = brainFrame == null || brainFrame.brain == null ? 0f : brainFrame.brain.DNa02_L_Hz;
            Debug.Log(string.Format(
                CultureInfo.InvariantCulture,
                "FLYLOCOMOTION_STATUS source={0} forward={1:0.###} turn={2:0.###} phase={3:0.###} leftScale={4:0.###} rightScale={5:0.###} position=({6:0.###},{7:0.###},{8:0.###}) velocity=({9:0.###},{10:0.###},{11:0.###}) yawRate={12:0.###} contacts={13} foot0=({14:0.###},{15:0.###},{16:0.###}) brainFrame={17} DNp09={18:0.###} DNa02_R={19:0.###} DNa02_L={20:0.###}",
                controller.MotorSource == null ? "none" : controller.MotorSource.SourceName,
                motor.forward,
                motor.turn,
                controller.Phase,
                controller.LeftGaitScale,
                controller.RightGaitScale,
                flyBody.Position.x,
                flyBody.Position.y,
                flyBody.Position.z,
                velocity.x,
                velocity.y,
                velocity.z,
                angularVelocity.y,
                flyBody.GroundContactCount,
                flyBody.FirstFootProbePosition.x,
                flyBody.FirstFootProbePosition.y,
                flyBody.FirstFootProbePosition.z,
                frameSequence,
                dNp09,
                dNa02R,
                dNa02L));
        }

        private void OnGUI()
        {
            if (controller == null)
            {
                return;
            }

            GUILayout.BeginArea(new Rect(Screen.width - 330f, 12f, 318f, 430f), GUI.skin.box);
            GUILayout.Label("Fly Locomotion Sandbox");
            GUILayout.Label("Source: " + (controller.MotorSource == null ? "none" : controller.MotorSource.SourceName));
            GUILayout.Label("Motor  forward=" + Format(controller.CurrentMotor.forward) + " turn=" + Format(controller.CurrentMotor.turn));
            GUILayout.Label("CPG phase=" + Format(controller.Phase) + " Hz=" + Format(flyBody.Config == null ? 0f : flyBody.Config.gaitFrequencyHz));
            GUILayout.Label("Gait  left=" + Format(controller.LeftGaitScale) + " right=" + Format(controller.RightGaitScale));
            GUILayout.Label("Velocity=" + FormatVector(flyBody.LinearVelocity) + " yaw=" + Format(flyBody.AngularVelocity.y));
            GUILayout.Label("Ground contacts=" + flyBody.GroundContactCount + "/6");

            GUILayout.Space(6f);
            GUILayout.Label("Mock checkpoint");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("STOP")) mockSource.SetStop();
            if (GUILayout.Button("FORWARD")) mockSource.SetStraight();
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("CURVE L")) mockSource.SetCurveLeft();
            if (GUILayout.Button("CURVE R")) mockSource.SetCurveRight();
            GUILayout.EndHorizontal();

            GUILayout.Space(6f);
            if (GUILayout.Button("Use Brain + Connect"))
            {
                ActivateBrainSource();
            }

            if (brainClient != null)
            {
                GUILayout.Label("Brain: " + brainClient.ConnectionState + " / " + brainClient.ServerState);
                BrainFrame frame = brainSource == null ? null : brainSource.LatestFrame;
                if (frame != null && frame.brain != null && frame.motor != null)
                {
                    GUILayout.Label("DNp09=" + Format(frame.brain.DNp09_Hz) + " R=" + Format(frame.brain.DNa02_R_Hz) + " L=" + Format(frame.brain.DNa02_L_Hz));
                    GUILayout.Label("Brain motor=" + Format(frame.motor.forward) + ", " + Format(frame.motor.turn));
                }
            }

            GUILayout.EndArea();
        }

        private void ActivateBrainSource()
        {
            if (brainSource == null || brainClient == null)
            {
                return;
            }

            brainClient.enabled = true;
            brainSource.enabled = true;
            brainClient.Connect();
            controller.SetMotorSource(brainSource);
            Debug.Log("FLYLOCOMOTION_BRAIN_SOURCE_ACTIVE");
        }

        private static string Format(float value)
        {
            return value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        private static string FormatVector(Vector3 value)
        {
            return "(" + Format(value.x) + "," + Format(value.y) + "," + Format(value.z) + ")";
        }

        private static bool HasCommandLineFlag(string name)
        {
            string[] arguments = System.Environment.GetCommandLineArgs();
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
            string[] arguments = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name)
                {
                    return arguments[i + 1];
                }
            }

            return string.Empty;
        }
    }
}
