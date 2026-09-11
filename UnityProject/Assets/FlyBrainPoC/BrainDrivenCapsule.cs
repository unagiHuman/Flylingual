using UnityEngine;

namespace FlyBrainPoC
{
    [RequireComponent(typeof(Rigidbody))]
    public class BrainDrivenCapsule : MonoBehaviour
    {
        [SerializeField] private BrainTcpClient brainClient;
        [SerializeField] private Rigidbody body;
        [SerializeField] private float forwardAcceleration = 4f;
        [SerializeField] private float turnAcceleration = 2f;
        [SerializeField] private float damping = 1.5f;
        [SerializeField] private float staleFrameTimeoutSeconds = 0.75f;

        public BrainTcpClient BrainClient => brainClient;

        public void Configure(BrainTcpClient client, Rigidbody rigidbody)
        {
            brainClient = client;
            body = rigidbody;
        }

        private void Awake()
        {
            if (body == null)
            {
                body = GetComponent<Rigidbody>();
            }
        }

        private void FixedUpdate()
        {
            float forward = 0f;
            float turn = 0f;
            bool freshFrame = false;
            if (brainClient != null && brainClient.TryGetLatestFrame(out BrainFrame frame, out double ageSeconds))
            {
                freshFrame = ageSeconds <= staleFrameTimeoutSeconds;
                if (freshFrame && frame.motor != null)
                {
                    // The actuator consumes only decoded BrainFrame.motor values.
                    // It intentionally does not inspect requestedAction.
                    forward = frame.motor.forward;
                    turn = frame.motor.turn;
                }
            }

            body.AddForce(transform.forward * (forward * forwardAcceleration), ForceMode.Acceleration);
            body.AddTorque(Vector3.up * (turn * turnAcceleration), ForceMode.Acceleration);

            if (!freshFrame)
            {
                body.AddForce(-body.linearVelocity * damping, ForceMode.Acceleration);
                body.AddTorque(-body.angularVelocity * damping, ForceMode.Acceleration);
            }
        }

        private void OnValidate()
        {
            forwardAcceleration = Mathf.Max(0f, forwardAcceleration);
            turnAcceleration = Mathf.Max(0f, turnAcceleration);
            damping = Mathf.Max(0f, damping);
            staleFrameTimeoutSeconds = Mathf.Max(0.05f, staleFrameTimeoutSeconds);
        }
    }
}
