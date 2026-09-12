using System;
using System.Collections.Generic;
using System.Diagnostics;
using FlyBrainPoC;
using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.Video
{
    /// <summary>Passive video provenance observer; it never connects, sends, or controls Brain state.</summary>
    public sealed class UnityVideoBrainIdentity : MonoBehaviour
    {
        const double RescanSeconds = 1.0;
        const int MaxClients = 8;
        readonly Dictionary<BrainTcpClient, ClientObservation> observations = new Dictionary<BrainTcpClient, ClientObservation>();
        FlyLocomotionController[] controllers = new FlyLocomotionController[0];
        BrainMotorSource[] sources = new BrainMotorSource[0];
        BrainTcpClient[] clients = new BrainTcpClient[0];
        long nextRescanTicks, activeSinceTicks;
        BrainTcpClient activeClient;
        BrainMotorSource activeSource;

        [Serializable] public sealed class SnapshotData
        {
            public string instanceId, sessionId, backendId, datasetId, configHash, graphHash, sourceHash;
            public double frameAgeMs;
            public int frameSequence;
        }

        public void Initialize() => ReconcileClients();
        void Awake() => ReconcileClients();
        void OnEnable() { if (observations.Count == 0) ReconcileClients(); }

        void Update()
        {
            if (Stopwatch.GetTimestamp() >= nextRescanTicks) ReconcileClients();
            foreach (var pair in observations)
                if (pair.Key == null || pair.Key.ConnectionState != "CONNECTED") pair.Value.Invalidate();
            RefreshActiveBinding();
        }

        public SnapshotData Snapshot()
        {
            if (Stopwatch.GetTimestamp() >= nextRescanTicks) ReconcileClients();
            BrainTcpClient client = RefreshActiveBinding();
            if (client == null || client.ConnectionState != "CONNECTED" || !observations.TryGetValue(client, out ClientObservation observation)) return null;
            BrainFrame typed = client.LatestBrainFrame;
            long now = Stopwatch.GetTimestamp();
            lock (observation.Sync)
            {
                RawFrame frame = observation.Frame;
                RawStatus status = observation.Status;
                if (frame == null || status == null || typed == null || frame.Sequence != typed.sequence || frame.Ticks < activeSinceTicks ||
                    !frame.MatchesStatus(status.Identity)) return null;
                return new SnapshotData
                {
                    instanceId = status.Identity.InstanceId, sessionId = status.Identity.SessionId,
                    backendId = status.Identity.BackendId, datasetId = status.Identity.DatasetId,
                    configHash = status.Identity.ConfigHash, graphHash = status.Identity.GraphHash, sourceHash = status.Identity.SourceHash,
                    // Keep provenance when Brain pauses; the receiver independently expires
                    // freshness at 750 ms without repeatedly renegotiating the video stream.
                    frameAgeMs = Math.Min(86400000, Math.Max(0, (now - frame.Ticks) * 1000.0 / Stopwatch.Frequency)), frameSequence = frame.Sequence,
                };
            }
        }

        void ReconcileClients()
        {
            nextRescanTicks = Stopwatch.GetTimestamp() + (long)(RescanSeconds * Stopwatch.Frequency);
            controllers = FindObjectsByType<FlyLocomotionController>(FindObjectsInactive.Exclude, FindObjectsSortMode.None);
            sources = FindObjectsByType<BrainMotorSource>(FindObjectsInactive.Exclude, FindObjectsSortMode.None);
            clients = FindObjectsByType<BrainTcpClient>(FindObjectsInactive.Exclude, FindObjectsSortMode.None);
            var live = new HashSet<BrainTcpClient>();
            for (int i = 0; i < clients.Length; i++)
            {
                BrainTcpClient client = clients[i];
                if (client == null || !client.isActiveAndEnabled) continue;
                live.Add(client);
                if (observations.ContainsKey(client) || observations.Count >= MaxClients) continue;
                var observation = new ClientObservation();
                observation.Handler = line => ObserveLine(observation, line);
                client.ReceivedLine += observation.Handler;
                observations.Add(client, observation);
            }
            var removed = new List<BrainTcpClient>();
            foreach (var pair in observations) if (pair.Key == null || !live.Contains(pair.Key)) removed.Add(pair.Key);
            for (int i = 0; i < removed.Count; i++)
            {
                BrainTcpClient client = removed[i];
                if (client != null) client.ReceivedLine -= observations[client].Handler;
                observations.Remove(client);
                if (activeClient == client) { activeClient = null; activeSinceTicks = Stopwatch.GetTimestamp(); }
            }
        }

        BrainTcpClient RefreshActiveBinding()
        {
            int activeControllers = 0, activeSources = 0, activeClients = 0;
            BrainMotorSource source = null;
            BrainTcpClient client = null;
            for (int i = 0; i < controllers.Length; i++)
            {
                FlyLocomotionController controller = controllers[i];
                if (controller == null || !controller.isActiveAndEnabled) continue;
                activeControllers++;
                source = controller.MotorSource as BrainMotorSource;
                client = source == null || !source.isActiveAndEnabled ? null : source.BrainClient;
            }
            for (int i = 0; i < sources.Length; i++) if (sources[i] != null && sources[i].isActiveAndEnabled) activeSources++;
            for (int i = 0; i < clients.Length; i++) if (clients[i] != null && clients[i].isActiveAndEnabled) activeClients++;
            if (activeControllers != 1 || activeSources != 1 || activeClients != 1 || source == null || client == null || !client.isActiveAndEnabled)
            {
                if (activeClient != null) { activeClient = null; activeSinceTicks = Stopwatch.GetTimestamp(); }
                return null;
            }
            if (client != activeClient || source != activeSource) { activeClient = client; activeSource = source; activeSinceTicks = Stopwatch.GetTimestamp(); }
            return activeClient;
        }

        void OnDisable() => Unsubscribe();
        void OnDestroy() => Unsubscribe();

        void Unsubscribe()
        {
            foreach (var pair in observations) if (pair.Key != null) pair.Key.ReceivedLine -= pair.Value.Handler;
            observations.Clear();
            activeClient = null;
            activeSource = null;
        }

        // ReceivedLine runs on a TCP task. This method avoids Unity object APIs.
        static void ObserveLine(ClientObservation observation, string line)
        {
            lock (observation.Sync) observation.Accept(line, Stopwatch.GetTimestamp());
        }

        sealed class ClientObservation
        {
            public readonly object Sync = new object();
            public Action<string> Handler;
            public RawStatus Status;
            public RawFrame Frame;
            int lastSequence = -1;

            public void Accept(string line, long ticks)
            {
                if (!RawJson.TryEnvelope(line, out RawEnvelope envelope)) { Frame = null; return; }
                if (envelope.type == "error") { Status = null; Frame = null; lastSequence = -1; return; }
                if (envelope.type == "status")
                {
                    if (!RawJson.TryStatus(line, out RawStatus status)) { Status = null; Frame = null; lastSequence = -1; return; }
                    if (Status == null || !Status.Identity.Matches(status.Identity)) { Frame = null; lastSequence = -1; }
                    status.Ticks = ticks; Status = status; return;
                }
                if (envelope.type != "brain_frame") return;
                if (Status == null || !RawJson.TryFrame(line, out RawFrame frame) || !frame.MatchesStatus(Status.Identity) || frame.Sequence <= lastSequence)
                { Frame = null; return; }
                frame.Ticks = ticks; Frame = frame; lastSequence = frame.Sequence;
            }

            public void Invalidate() { lock (Sync) { Status = null; Frame = null; lastSequence = -1; } }
        }

        sealed class RawStatus { public Identity Identity; public long Ticks; }
        sealed class RawFrame
        {
            public string InstanceId, SessionId, BackendId, DatasetId;
            public int Sequence; public long Ticks;
            public bool MatchesStatus(Identity status) => status != null && InstanceId == status.InstanceId && SessionId == status.SessionId &&
                BackendId == status.BackendId && DatasetId == status.DatasetId;
        }
        sealed class Identity
        {
            public string InstanceId, SessionId, BackendId, DatasetId, ConfigHash, GraphHash, SourceHash;
            public bool Matches(Identity other) => other != null && InstanceId == other.InstanceId && SessionId == other.SessionId &&
                BackendId == other.BackendId && DatasetId == other.DatasetId && ConfigHash == other.ConfigHash &&
                GraphHash == other.GraphHash && SourceHash == other.SourceHash;
        }

        [Serializable] sealed class RawEnvelope { public string type; }
        [Serializable] sealed class RawStatusPayload { public string instanceId, sessionId, backendId, datasetId, configHash, graphHash, sourceHash; }
        [Serializable] sealed class RawFramePayload { public int sequence = -1; public RawMetadata metadata; public RawMotor motor; }
        [Serializable] sealed class RawMetadata { public string instanceId, sessionId, backendId, datasetId, mode; }
        [Serializable] sealed class RawMotor { public float forward = float.NaN, turn = float.NaN; }

        static class RawJson
        {
            public static bool TryEnvelope(string line, out RawEnvelope envelope)
            {
                envelope = null;
                try { envelope = JsonUtility.FromJson<RawEnvelope>(line); }
                catch (Exception) { return false; }
                return envelope != null && (envelope.type == "status" || envelope.type == "brain_frame" || envelope.type == "error" || envelope.type == "ack");
            }
            public static bool TryStatus(string line, out RawStatus status)
            {
                status = null;
                try
                {
                    RawStatusPayload value = JsonUtility.FromJson<RawStatusPayload>(line);
                    if (value == null || !Text(value.instanceId) || !Text(value.sessionId) || !Text(value.backendId) || !Text(value.datasetId) ||
                        !Text(value.configHash) || !Text(value.graphHash) || !Text(value.sourceHash)) return false;
                    status = new RawStatus { Identity = new Identity { InstanceId = value.instanceId, SessionId = value.sessionId,
                        BackendId = value.backendId, DatasetId = value.datasetId, ConfigHash = value.configHash,
                        GraphHash = value.graphHash, SourceHash = value.sourceHash } };
                    return true;
                }
                catch (Exception) { return false; }
            }
            public static bool TryFrame(string line, out RawFrame frame)
            {
                frame = null;
                try
                {
                    RawFramePayload value = JsonUtility.FromJson<RawFramePayload>(line);
                    if (value == null || value.sequence < 0 || value.metadata == null || value.motor == null ||
                        !Text(value.metadata.instanceId) || !Text(value.metadata.sessionId) || !Text(value.metadata.backendId) || !Text(value.metadata.datasetId) ||
                        float.IsNaN(value.motor.forward) || float.IsInfinity(value.motor.forward) || float.IsNaN(value.motor.turn) || float.IsInfinity(value.motor.turn) ||
                        value.motor.forward < 0f || value.motor.forward > 1f || value.motor.turn < -1f || value.motor.turn > 1f ||
                        value.metadata.mode == "REPLAY" || value.metadata.mode == "MOCK") return false;
                    frame = new RawFrame { Sequence = value.sequence, InstanceId = value.metadata.instanceId, SessionId = value.metadata.sessionId,
                        BackendId = value.metadata.backendId, DatasetId = value.metadata.datasetId };
                    return true;
                }
                catch (Exception) { return false; }
            }
            static bool Text(string value)
            {
                if (string.IsNullOrEmpty(value) || value.Length > 128) return false;
                for (int i = 0; i < value.Length; i++) if (value[i] < ' ' || value[i] > '~') return false;
                return true;
            }
        }
    }
}
