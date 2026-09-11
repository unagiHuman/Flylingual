using System.Globalization;
using UnityEngine;

namespace FlyBrainPoC
{
    public class BrainControlPanel : MonoBehaviour
    {
        [SerializeField] private BrainTcpClient brainClient;
        [SerializeField] private int width = 360;
        [SerializeField] private int height = 520;

        private GUIStyle labelStyle;
        private GUIStyle titleStyle;
        private int lastLoggedFrameSequence = -1;

        public void Configure(BrainTcpClient client)
        {
            brainClient = client;
        }

        private void Update()
        {
            if (brainClient == null)
            {
                return;
            }

            BrainFrame frame = brainClient.LatestBrainFrame;
            if (frame == null || frame.sequence == lastLoggedFrameSequence)
            {
                return;
            }

            lastLoggedFrameSequence = frame.sequence;
            if (frame.appliedRequestId > 0)
            {
                float forward = frame.motor == null ? 0f : frame.motor.forward;
                float turn = frame.motor == null ? 0f : frame.motor.turn;
                float dNp09 = frame.brain == null ? 0f : frame.brain.DNp09_Hz;
                float dNa02R = frame.brain == null ? 0f : frame.brain.DNa02_R_Hz;
                float dNa02L = frame.brain == null ? 0f : frame.brain.DNa02_L_Hz;
                Debug.Log(string.Format(
                    "FLYBRAIN_ACTION_APPLIED requestId={0} action={1} sequence={2} forward={3:0.###} turn={4:0.###} DNp09_Hz={5:0.###} DNa02_R_Hz={6:0.###} DNa02_L_Hz={7:0.###} stepWallTimeMs={8:0.###}",
                    frame.appliedRequestId,
                    frame.requestedAction,
                    frame.sequence,
                    forward,
                    turn,
                    dNp09,
                    dNa02R,
                    dNa02L,
                    frame.performance == null ? 0f : frame.performance.stepWallTimeMs));
            }
        }

        private void OnGUI()
        {
            if (brainClient == null)
            {
                return;
            }

            HandleKeyboardAction(Event.current);
            EnsureStyles();
            GUILayout.BeginArea(new Rect(12, 12, width, height), GUI.skin.box);
            GUILayout.Label("FlyBrain Unity PoC", titleStyle);
            GUILayout.Label("Connection: " + brainClient.ConnectionState, labelStyle);
            GUILayout.Label("Server: " + brainClient.ServerState, labelStyle);
            GUILayout.Label("Requested: " + brainClient.RequestedAction, labelStyle);

            GUILayout.Space(6);
            DrawActionButton("STOP", "STOP");
            DrawActionButton("F", "FORWARD");
            GUILayout.BeginHorizontal();
            DrawActionButton("L", "TURN_L");
            DrawActionButton("R", "TURN_R");
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            DrawActionButton("F + L", "FORWARD_L");
            DrawActionButton("F + R", "FORWARD_R");
            GUILayout.EndHorizontal();

            BrainFrame frame = brainClient.LatestBrainFrame;
            GUILayout.Space(8);
            if (frame == null)
            {
                GUILayout.Label("BrainFrame: none", labelStyle);
            }
            else
            {
                GUILayout.Label("Frame sequence: " + frame.sequence, labelStyle);
                GUILayout.Label("Applied requestId: " + (frame.appliedRequestId > 0 ? frame.appliedRequestId.ToString() : "none"), labelStyle);
                GUILayout.Label("Forward: " + Format(frame.motor == null ? 0f : frame.motor.forward), labelStyle);
                GUILayout.Label("Turn: " + Format(frame.motor == null ? 0f : frame.motor.turn), labelStyle);
                GUILayout.Label("DNp09: " + Format(frame.brain == null ? 0f : frame.brain.DNp09_Hz) + " Hz", labelStyle);
                GUILayout.Label("DNa02_R: " + Format(frame.brain == null ? 0f : frame.brain.DNa02_R_Hz) + " Hz", labelStyle);
                GUILayout.Label("DNa02_L: " + Format(frame.brain == null ? 0f : frame.brain.DNa02_L_Hz) + " Hz", labelStyle);
                GUILayout.Label("Brain step: " + Format(frame.performance == null ? 0f : frame.performance.stepWallTimeMs) + " ms", labelStyle);
                GUILayout.Label("Unity E2E: " + FormatLatency(brainClient.LatestLatencyMs), labelStyle);
            }

            if (!string.IsNullOrEmpty(brainClient.LastError))
            {
                GUILayout.Label("Error: " + brainClient.LastError, labelStyle);
            }
            GUILayout.EndArea();
        }

        private void HandleKeyboardAction(Event currentEvent)
        {
            if (currentEvent == null || currentEvent.type != EventType.KeyDown || currentEvent.isKey == false)
            {
                return;
            }

            switch (currentEvent.keyCode)
            {
                case KeyCode.W:
                    brainClient.SetAction("FORWARD");
                    currentEvent.Use();
                    break;
                case KeyCode.A:
                    brainClient.SetAction("TURN_L");
                    currentEvent.Use();
                    break;
                case KeyCode.D:
                    brainClient.SetAction("TURN_R");
                    currentEvent.Use();
                    break;
                case KeyCode.S:
                case KeyCode.Space:
                    brainClient.SetAction("STOP");
                    currentEvent.Use();
                    break;
                case KeyCode.Alpha1:
                    brainClient.SetAction("STOP");
                    currentEvent.Use();
                    break;
                case KeyCode.Alpha2:
                    brainClient.SetAction("FORWARD");
                    currentEvent.Use();
                    break;
                case KeyCode.Alpha3:
                    brainClient.SetAction("TURN_L");
                    currentEvent.Use();
                    break;
                case KeyCode.Alpha4:
                    brainClient.SetAction("TURN_R");
                    currentEvent.Use();
                    break;
                case KeyCode.Alpha5:
                    brainClient.SetAction("FORWARD_L");
                    currentEvent.Use();
                    break;
                case KeyCode.Alpha6:
                    brainClient.SetAction("FORWARD_R");
                    currentEvent.Use();
                    break;
            }
        }

        private void DrawActionButton(string label, string action)
        {
            if (GUILayout.Button(label, GUILayout.Height(36)))
            {
                brainClient.SetAction(action);
            }
        }

        private void EnsureStyles()
        {
            if (labelStyle != null)
            {
                return;
            }

            labelStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 14,
                wordWrap = true
            };
            titleStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 18,
                fontStyle = FontStyle.Bold
            };
        }

        private static string Format(float value)
        {
            return value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        private static string FormatLatency(double value)
        {
            return value < 0 ? "n/a" : value.ToString("0.0", CultureInfo.InvariantCulture) + " ms";
        }
    }
}
