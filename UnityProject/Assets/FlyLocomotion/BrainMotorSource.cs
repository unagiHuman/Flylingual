using FlyBrainPoC;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class BrainMotorSource : FlyMotorSource
    {
        [SerializeField] private BrainTcpClient brainClient;
        [SerializeField] private float staleFrameTimeoutSeconds = 0.75f;

        public BrainTcpClient BrainClient => brainClient;
        public bool HasFreshFrame { get; private set; }
        public BrainFrame LatestFrame { get; private set; }
        public double LatestFrameAgeSeconds { get; private set; } = double.PositiveInfinity;

        public override string SourceName => "BrainFrame";

        public void Configure(BrainTcpClient client)
        {
            brainClient = client;
        }

        public override FlyMotorCommand GetMotorCommand()
        {
            HasFreshFrame = false;
            LatestFrame = null;
            LatestFrameAgeSeconds = double.PositiveInfinity;

            if (brainClient == null || !brainClient.TryGetLatestFrame(out BrainFrame frame, out double ageSeconds))
            {
                return FlyMotorCommand.Stop;
            }

            LatestFrame = frame;
            LatestFrameAgeSeconds = ageSeconds;
            HasFreshFrame = ageSeconds <= staleFrameTimeoutSeconds && frame.motor != null;
            return HasFreshFrame
                ? new FlyMotorCommand(frame.motor.forward, frame.motor.turn)
                : FlyMotorCommand.Stop;
        }

        private void OnValidate()
        {
            staleFrameTimeoutSeconds = Mathf.Max(0.05f, staleFrameTimeoutSeconds);
        }
    }
}
