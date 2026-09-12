using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using FlyBrainPoC;
using UnityEngine;

namespace FlyBrainVisualization
{
    /// <summary>Passive subscriber to the game's existing connection. Never sends or connects.</summary>
    public sealed class NeuralActivityObserver : MonoBehaviour
    {
        [SerializeField] private BrainTcpClient source;
        [SerializeField] private TextAsset atlasAsset;
        [SerializeField] private NeuralPointCloud pointCloud;
        [SerializeField, Range(.1f, .75f)] private float staleSeconds = .75f;
        [SerializeField] private bool bindSingleExistingClient = true;

        private const int MaxLineLength = 2 * 1024 * 1024;
        private readonly object incomingLock = new object();
        private readonly Queue<Received> incoming = new Queue<Received>();
        private readonly Dictionary<string, int> indices = new Dictionary<string, int>(StringComparer.Ordinal);
        private readonly HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);
        private NeuralAtlas atlas;
        private BrainTcpClient subscribedSource;
        private float[] spikes, delta;
        private bool[] observed;
        private string identity;
        private string expectedInstance, expectedSession;
        private long lastSequence = -1;
        private double lastBrainTime = -1, receivedAt = -1;
        private bool accepting, oversizedLine, fresh;
        private float nextSourceSearch;

        private struct Received { public string line; public double time; }
        private static double Clock => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency;
        public string State { get; private set; } = "NO ATLAS";
        public string Dataset => atlas == null ? "UNAVAILABLE" : atlas.datasetId;
        public string Backend { get; private set; } = "UNKNOWN";
        public string Mode { get; private set; } = "UNKNOWN";
        public bool Ready { get; private set; }
        public int PointCount => atlas == null ? 0 : atlas.neurons.Length;
        public int ObservedCount { get; private set; }
        public int ActiveCount { get; private set; }
        public long SpikeCount { get; private set; }
        public int DroppedFrames { get; private set; }
        public long Sequence => lastSequence;
        public string SessionIdentity => identity;
        public double BrainTimeMs => lastBrainTime;
        public double FrameAgeMs => receivedAt < 0 ? -1 : (Clock - receivedAt) * 1000;
        public float WindowMs { get; private set; }
        public bool IsFresh => fresh;
        public event Action FrameApplied;

        public void Configure(BrainTcpClient client, TextAsset data, NeuralPointCloud cloud)
        {
            Unsubscribe();
            source = client; atlasAsset = data; pointCloud = cloud;
            if (isActiveAndEnabled) { LoadAtlas(); Subscribe(); }
        }

        private void OnEnable()
        {
            lock (incomingLock) accepting = true;
            LoadAtlas();
            Subscribe();
        }

        private void LoadAtlas()
        {
            atlas = null; indices.Clear(); ResetIdentity();
            if (pointCloud == null) pointCloud = GetComponentInChildren<NeuralPointCloud>(true);
            if (pointCloud != null) pointCloud.SetPoints(null);
            if (atlasAsset == null) atlasAsset = Resources.Load<TextAsset>("BrainVisualization/malecns-atlas");
            if (atlasAsset == null || pointCloud == null) { Invalidate("NO ATLAS"); return; }
            try
            {
                var candidate = JsonUtility.FromJson<NeuralAtlas>(atlasAsset.text);
                if (candidate == null || candidate.schemaVersion != 1 || candidate.datasetId != "male-cns:v1.0" ||
                    string.IsNullOrEmpty(candidate.atlasId) || candidate.atlasId.Length != 64 ||
                    candidate.neurons == null || candidate.neurons.Length == 0 || candidate.neurons.Length > 65536)
                    throw new FormatException();
                var positions = new Vector3[candidate.neurons.Length];
                for (int i = 0; i < positions.Length; i++)
                {
                    var n = candidate.neurons[i];
                    if (n == null || string.IsNullOrEmpty(n.id) || !Finite(n.x) || !Finite(n.y) || !Finite(n.z) ||
                        Mathf.Max(Mathf.Abs(n.x), Mathf.Abs(n.y), Mathf.Abs(n.z)) > 100 || indices.ContainsKey(n.id))
                        throw new FormatException();
                    indices.Add(n.id, i); positions[i] = new Vector3(n.x, n.y, n.z);
                }
                atlas = candidate;
                spikes = new float[positions.Length]; delta = new float[positions.Length]; observed = new bool[positions.Length];
                pointCloud.SetPoints(positions);
                Invalidate("WAITING FOR BRAIN");
            }
            catch (Exception)
            {
                atlas = null; indices.Clear(); Invalidate("INVALID ATLAS");
                UnityEngine.Debug.LogWarning("NEURAL_VIS_ATLAS_INVALID: regenerate the atlas using the exporter", this);
            }
        }

        private void Subscribe()
        {
            if (subscribedSource == source && subscribedSource != null) return;
            Unsubscribe();
            if (source == null && bindSingleExistingClient)
            {
                var clients = FindObjectsByType<BrainTcpClient>();
                if (clients.Length == 1) source = clients[0];
            }
            if (source == null) { if (atlas != null) Invalidate("SELECT BRAIN CLIENT"); return; }
            subscribedSource = source;
            subscribedSource.ReceivedLine += Receive;
        }

        // ReceivedLine runs on the TCP worker. Do no Unity calls or parsing on that thread.
        private void Receive(string line)
        {
            lock (incomingLock)
            {
                if (!accepting || line == null) return;
                if (line.Length > MaxLineLength) { oversizedLine = true; return; }
                if (incoming.Count == 4) { incoming.Dequeue(); DroppedFrames++; }
                incoming.Enqueue(new Received { line = line, time = Clock });
            }
        }

        private void Update()
        {
            if (subscribedSource != source || (source == null && Time.unscaledTime >= nextSourceSearch))
            { nextSourceSearch = Time.unscaledTime + 1; Subscribe(); }
            if (subscribedSource != null && subscribedSource.ConnectionState != "CONNECTED")
            {
                lock (incomingLock) incoming.Clear();
                ResetIdentity();
                if (atlas != null) Invalidate("DISCONNECTED");
                return;
            }
            Received latest = default;
            bool haveFrame = false;
            for (int i = 0; i < 4; i++)
            {
                Received item;
                lock (incomingLock)
                {
                    if (oversizedLine) { oversizedLine = false; incoming.Clear(); haveFrame = false; Invalidate("FRAME TOO LARGE"); }
                    if (incoming.Count == 0) break;
                    item = incoming.Dequeue();
                }
                // Parse the small envelope first; only one full neuron payload is materialized per Update.
                try
                {
                    var envelope = JsonUtility.FromJson<MessageEnvelope>(item.line);
                    if (envelope != null && envelope.type == "brain_frame")
                    {
                        if (haveFrame) { lock (incomingLock) DroppedFrames++; }
                        latest = item; haveFrame = true;
                    }
                    else
                    {
                        if (envelope == null || envelope.type == "status" || envelope.type == "error") haveFrame = false;
                        Process(item);
                    }
                }
                catch (Exception) { haveFrame = false; Invalidate("INVALID FRAME"); }
            }
            if (haveFrame) Process(latest);
            if (fresh && Clock - receivedAt > Mathf.Clamp(staleSeconds, .1f, .75f)) Invalidate("STALE");
        }

        private void Process(Received item)
        {
            if (atlas == null) return;
            try
            {
                var frame = JsonUtility.FromJson<NeuralEnvelope>(item.line);
                if (frame == null) { Invalidate("INVALID FRAME"); return; }
                if (frame.type == "status")
                {
                    // Repeated status/heartbeats must not make the same frame eligible again.
                    if (string.IsNullOrEmpty(frame.instanceId) || string.IsNullOrEmpty(frame.sessionId) || frame.datasetId != atlas.datasetId)
                    { ResetIdentity(); Invalidate("WAITING FOR SESSION IDENTITY"); return; }
                    if (expectedInstance != frame.instanceId || expectedSession != frame.sessionId)
                    {
                        ResetIdentity(); expectedInstance = frame.instanceId; expectedSession = frame.sessionId;
                        Invalidate("WAITING FOR BRAIN");
                    }
                    return;
                }
                if (frame.type == "error") { Invalidate("BRAIN ERROR"); return; }
                if (frame.type != "brain_frame") return;
                var meta = frame.metadata;
                if (meta == null || meta.datasetId != atlas.datasetId || string.IsNullOrEmpty(meta.backendId) ||
                    string.IsNullOrEmpty(meta.instanceId) || string.IsNullOrEmpty(meta.sessionId) ||
                    (meta.mode != "LIVE" && meta.mode != "REPLAY" && meta.mode != "MOCK"))
                { Invalidate("DATASET / IDENTITY MISMATCH"); return; }
                if (meta.instanceId != expectedInstance || meta.sessionId != expectedSession)
                { Invalidate("WAITING FOR MATCHING SESSION STATUS"); return; }
                string nextIdentity = meta.instanceId + "/" + meta.sessionId + "/" + meta.datasetId + "/" + meta.mode;
                if (identity != null && identity != nextIdentity) { Invalidate("SESSION MODE CHANGED"); return; }
                identity = nextIdentity;
                Backend = meta.backendId; Mode = meta.mode; Ready = meta.ready;
                if (frame.sequence < 0 || double.IsNaN(frame.brainTimeMs) || double.IsInfinity(frame.brainTimeMs) || frame.brainTimeMs < 0)
                { Invalidate("INVALID BRAIN TIME"); return; }
                // Duplicates never refresh age or retrigger glow. Regressions fail closed until a new session.
                if (frame.sequence == lastSequence) return;
                if (frame.sequence < lastSequence || frame.brainTimeMs <= lastBrainTime)
                { Invalidate("OUT OF ORDER"); return; }
                if (Clock - item.time > Mathf.Clamp(staleSeconds, .1f, .75f)) { Invalidate("STALE"); return; }

                Array.Clear(spikes, 0, spikes.Length); Array.Clear(observed, 0, observed.Length);
                for (int i = 0; i < delta.Length; i++) delta[i] = float.NaN;
                int measured = 0, active = 0; long total = 0;
                bool hasSpikes = frame.visualization != null;
                float window = 50;
                if (hasSpikes)
                {
                    var v = frame.visualization;
                    if (v.schemaVersion != 1 || v.atlasId != atlas.atlasId || v.metric != "window_spike_count" ||
                        !Finite(v.windowMs) || v.windowMs <= 0 || v.windowMs > 1000 || v.bodyIds == null || v.spikeCounts == null ||
                        v.bodyIds.Length != spikes.Length || v.bodyIds.Length != v.spikeCounts.Length)
                    { Invalidate("SPIKE PAYLOAD MISMATCH"); return; }
                    window = v.windowMs; seen.Clear();
                    for (int i = 0; i < v.bodyIds.Length; i++)
                    {
                        if (v.bodyIds[i] == null || !indices.TryGetValue(v.bodyIds[i], out int index) || !seen.Add(v.bodyIds[i]) ||
                            v.spikeCounts[i] < 0 || v.spikeCounts[i] > 1000000)
                        { Invalidate("INVALID SPIKE DATA"); return; }
                        spikes[index] = v.spikeCounts[i]; observed[index] = true; measured++;
                        total += v.spikeCounts[i]; if (v.spikeCounts[i] > 0) active++;
                    }
                }
                if (frame.raw != null && (frame.raw.bodyIds != null || frame.raw.deltaV != null))
                {
                    var raw = frame.raw;
                    if (raw.bodyIds == null || raw.deltaV == null || raw.bodyIds.Length != raw.deltaV.Length || raw.bodyIds.Length > 65536)
                    { Invalidate("INVALID VOLTAGE DATA"); return; }
                    seen.Clear();
                    for (int i = 0; i < raw.bodyIds.Length; i++)
                    {
                        string id = raw.bodyIds[i].ToString(CultureInfo.InvariantCulture);
                        if (!seen.Add(id) || !Finite(raw.deltaV[i])) { Invalidate("INVALID VOLTAGE DATA"); return; }
                        if (!indices.TryGetValue(id, out int index)) continue; // Coordinates may be missing from the anatomical source.
                        delta[index] = raw.deltaV[i];
                        if (!observed[index]) { observed[index] = true; measured++; }
                    }
                }
                if (measured == 0) { Invalidate("NO NEURON TELEMETRY"); return; }
                lastSequence = frame.sequence; lastBrainTime = frame.brainTimeMs; receivedAt = item.time;
                ObservedCount = measured; ActiveCount = active; SpikeCount = total; WindowMs = hasSpikes ? window : 0;
                fresh = true; State = hasSpikes ? "WINDOW SPIKES + VOLTAGE" : "VOLTAGE ONLY / NO SPIKE STREAM";
                pointCloud.SetActivity(hasSpikes ? spikes : null, delta, observed, window);
                FrameApplied?.Invoke();
            }
            catch (Exception)
            {
                Invalidate("INVALID FRAME"); // Never leak input or throw through the TCP event.
            }
        }

        private static bool Finite(float v) => !float.IsNaN(v) && !float.IsInfinity(v);
        private void ResetIdentity()
        {
            identity = null; lastSequence = -1; lastBrainTime = -1; receivedAt = -1;
            expectedInstance = expectedSession = null;
            Backend = "UNKNOWN"; Mode = "UNKNOWN"; Ready = false;
        }
        private void Invalidate(string reason)
        {
            State = reason;
            if (fresh || reason == "WAITING FOR BRAIN" || reason == "NO ATLAS") pointCloud?.ClearActivity();
            fresh = false; ObservedCount = ActiveCount = 0; SpikeCount = 0;
        }
        private void Unsubscribe()
        {
            if (subscribedSource != null) subscribedSource.ReceivedLine -= Receive;
            subscribedSource = null;
            lock (incomingLock) incoming.Clear();
            ResetIdentity();
        }
        private void OnDisable()
        {
            lock (incomingLock) accepting = false;
            Unsubscribe(); Invalidate("DISABLED");
        }
    }
}
