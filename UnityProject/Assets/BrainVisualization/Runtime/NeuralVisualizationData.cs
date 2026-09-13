using System;

namespace FlyBrainVisualization
{
    [Serializable] public sealed class NeuralAtlas
    {
        public int schemaVersion;
        public string datasetId, atlasId, coordinateSpace, sourceSha256, graphIdsSha256;
        public int totalGraphNeurons, omittedCoordinateCount;
        public NeuralAtlasPoint[] neurons;
    }

    [Serializable] public sealed class NeuralAtlasPoint
    {
        public string id;
        public float x, y, z;
    }

    // Separate DTOs keep the shared locomotion protocol and its serialized types untouched.
    [Serializable] internal sealed class NeuralEnvelope
    {
        public string type;
        public long sequence = -1;
        public double brainTimeMs = -1;
        public string datasetId, instanceId, sessionId;
        public string dataset;
        public int epoch;
        public bool brainConnected, switching, releaseUnknown;
        public NeuralMetadata metadata;
        public NeuralSpikeWindow visualization;
        public NeuralRawVoltage raw;
    }

    [Serializable] internal sealed class NeuralMetadata
    {
        public string datasetId, backendId, mode, instanceId, sessionId;
        public bool ready;
    }

    [Serializable] internal sealed class NeuralSpikeWindow
    {
        public int schemaVersion;
        public string atlasId, metric;
        public float windowMs;
        public string[] bodyIds;
        public int[] spikeCounts;
    }

    [Serializable] internal sealed class NeuralRawVoltage
    {
        public long[] bodyIds;
        public float[] deltaV;
    }
}
