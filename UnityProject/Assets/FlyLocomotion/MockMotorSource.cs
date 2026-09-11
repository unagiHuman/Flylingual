using System.Globalization;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class MockMotorSource : FlyMotorSource
    {
        [Header("Checkpoint A/B command")]
        [SerializeField, Range(0f, 1f)] private float forward = 1f;
        [SerializeField, Range(-1f, 1f)] private float turn;
        [SerializeField] private bool keyboardOverride;

        public float Forward => forward;
        public float Turn => turn;

        private void Awake()
        {
            string value;
            if (TryGetArgument("-flyMockForward", out value) && float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out float commandForward))
            {
                forward = Mathf.Clamp01(commandForward);
            }
            if (TryGetArgument("-flyMockTurn", out value) && float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out float commandTurn))
            {
                turn = Mathf.Clamp(commandTurn, -1f, 1f);
            }
        }

        public override FlyMotorCommand GetMotorCommand()
        {
            if (keyboardOverride)
            {
                float keyboardForward = Input.GetKey(KeyCode.W) ? 1f : 0f;
                float keyboardTurn = 0f;
                if (Input.GetKey(KeyCode.A)) keyboardTurn -= 0.5f;
                if (Input.GetKey(KeyCode.D)) keyboardTurn += 0.5f;
                return new FlyMotorCommand(keyboardForward, keyboardTurn);
            }

            return new FlyMotorCommand(forward, turn);
        }

        public void SetCommand(float nextForward, float nextTurn)
        {
            forward = Mathf.Clamp01(nextForward);
            turn = Mathf.Clamp(nextTurn, -1f, 1f);
        }

        public void SetStraight()
        {
            SetCommand(1f, 0f);
        }

        public void SetStop()
        {
            SetCommand(0f, 0f);
        }

        public void SetCurveLeft()
        {
            SetCommand(0.8f, -0.5f);
        }

        public void SetCurveRight()
        {
            SetCommand(0.8f, 0.5f);
        }

        private static bool TryGetArgument(string name, out string value)
        {
            string[] arguments = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name)
                {
                    value = arguments[i + 1];
                    return true;
                }
            }

            value = string.Empty;
            return false;
        }
    }
}
