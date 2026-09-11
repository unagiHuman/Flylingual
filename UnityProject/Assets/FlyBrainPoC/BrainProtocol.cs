using System;

namespace FlyBrainPoC
{
    [Serializable]
    public class MessageEnvelope
    {
        public string type;
    }

    [Serializable]
    public class SetActionCommand
    {
        public string type = "set_action";
        public int requestId;
        public string action;
        public double clientTimeMs;
    }

    [Serializable]
    public class StatusMessage
    {
        public string type;
        public string state;
        public string backend;
        public float windowMs;
        public float dtMs;
        public int networkRebuildCount;
        public int stateResetCount;
    }

    [Serializable]
    public class BrainFrame
    {
        public string type;
        public int sequence;
        // The server sends null when a frame has no newly applied request.
        // JsonUtility maps that nullable protocol value to its default int 0.
        public int appliedRequestId;
        public double appliedClientTimeMs;
        public string requestedAction;
        public float brainTimeMs;
        public MotorOutput motor;
        public BrainActivity brain;
        public PerformanceInfo performance;
        public BackendMetadata metadata;
        public PopulationReadout raw;
    }

    [Serializable] public class BackendMetadata
    {
        public string backendId, datasetId, model, motor_readout, mode;
        public bool ready;
    }
    [Serializable] public class PopulationReadout
    {
        public float forward_raw, turn_raw;
        public PopulationDelta populationDeltaMv;
        public float[] filteredRaw;
    }
    [Serializable] public class PopulationDelta
    {
        public BilateralPopulation forward, turn;
    }
    [Serializable] public class BilateralPopulation { public float R, L; }

    [Serializable]
    public class MotorOutput
    {
        public float forward;
        public float turn;
    }

    [Serializable]
    public class BrainActivity
    {
        public float DNp09_Hz;
        public float DNa02_R_Hz;
        public float DNa02_L_Hz;
        public float DNa02Difference_Hz;
    }

    [Serializable]
    public class PerformanceInfo
    {
        public float windowMs;
        public float stepWallTimeMs;
    }

    [Serializable]
    public class AckMessage
    {
        public string type;
        public int requestId;
        public string action;
        public bool accepted;
    }

    [Serializable]
    public class ErrorMessage
    {
        public string type;
        public int requestId;
        public string error;
        public string message;
        public string[] allowedActions;
    }
}
