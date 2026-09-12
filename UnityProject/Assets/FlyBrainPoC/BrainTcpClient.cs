using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace FlyBrainPoC
{
    public class BrainTcpClient : MonoBehaviour
    {
        [Header("Brain Server")]
        [SerializeField] private string host = "127.0.0.1";
        [SerializeField] private int port = 8765;
        [SerializeField] private bool connectOnStart = true;
        [SerializeField] private bool autoReconnect = true;
        [SerializeField] private float reconnectDelaySeconds = 1f;

        private readonly object dataLock = new object();
        private readonly SemaphoreSlim sendLock = new SemaphoreSlim(1, 1);
        private readonly Dictionary<int, long> pendingRequestTicks = new Dictionary<int, long>();

        private CancellationTokenSource cancellation;
        private Task connectionTask;
        private TcpClient tcpClient;
        private StreamWriter writer;

        private BrainFrame latestBrainFrame;
        private long latestFrameTicks;
        private StatusMessage latestStatus;
        private string connectionState = "DISCONNECTED";
        private string lastError = string.Empty;
        private string requestedAction = "STOP";
        private double latestLatencyMs = -1;
        private int nextRequestId = 1;
        private bool receiveOnly;
        private bool reportedBlockedSend;

        public string Host => host;
        public int Port => port;
        public event Action<string> ReceivedLine;
        public event Action<string> SentLine;
        public void EnableReceiveOnly()
        {
            if (connectionTask != null && !connectionTask.IsCompleted)
                throw new InvalidOperationException("Enable receive-only before connecting");
            lock (dataLock) receiveOnly = true;
        }

        public void ConfigureEndpoint(string address, int serverPort, bool reconnect)
        {
            if (connectionTask != null && !connectionTask.IsCompleted) throw new InvalidOperationException("Disconnect before configuring endpoint");
            host=address; port=serverPort; autoReconnect=reconnect; connectOnStart=false;
        }

        public string ConnectionState
        {
            get
            {
                lock (dataLock)
                {
                    return connectionState;
                }
            }
        }

        public string ServerState
        {
            get
            {
                lock (dataLock)
                {
                    return latestStatus == null ? "UNKNOWN" : latestStatus.state;
                }
            }
        }

        public string LastError
        {
            get
            {
                lock (dataLock)
                {
                    return lastError;
                }
            }
        }

        public string RequestedAction
        {
            get
            {
                lock (dataLock)
                {
                    return requestedAction;
                }
            }
        }

        public double LatestLatencyMs
        {
            get
            {
                lock (dataLock)
                {
                    return latestLatencyMs;
                }
            }
        }

        public BrainFrame LatestBrainFrame
        {
            get
            {
                lock (dataLock)
                {
                    return latestBrainFrame;
                }
            }
        }

        private void Start()
        {
            if (connectOnStart)
            {
                Connect();
            }
        }

        public void Connect()
        {
            if (connectionTask != null && !connectionTask.IsCompleted)
            {
                return;
            }

            cancellation?.Dispose();
            cancellation = new CancellationTokenSource();
            SetConnectionState("CONNECTING");
            connectionTask = Task.Run(() => ConnectionLoopAsync(cancellation.Token));
        }

        public void Disconnect()
        {
            cancellation?.Cancel();
            CloseSocket();
            SetConnectionState("DISCONNECTED");
        }

        public void SetAction(string action, bool force = false)
        {
            lock (dataLock)
            {
                if (receiveOnly)
                {
                    if (!reportedBlockedSend) UnityEngine.Debug.LogWarning("BRAIN_RECEIVE_ONLY_ACTION_BLOCKED");
                    reportedBlockedSend = true;
                    return;
                }
            }
            if (!IsAllowedAction(action))
            {
                SetError("Unity rejected unknown action: " + action);
                return;
            }

            lock (dataLock)
            {
                if (!force && requestedAction == action)
                {
                    return;
                }

                requestedAction = action;
            }

            int requestId;
            lock (dataLock)
            {
                requestId = nextRequestId++;
                pendingRequestTicks[requestId] = Stopwatch.GetTimestamp();
            }

            var command = new SetActionCommand
            {
                requestId = requestId,
                action = action,
                clientTimeMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
            };
            _ = SendCommandAsync(command, requestId);
        }

        public bool TryGetLatestFrame(out BrainFrame frame, out double ageSeconds)
        {
            lock (dataLock)
            {
                frame = latestBrainFrame;
                ageSeconds = frame == null
                    ? double.PositiveInfinity
                    : (Stopwatch.GetTimestamp() - latestFrameTicks) / (double)Stopwatch.Frequency;
                return frame != null;
            }
        }

        public bool TryGetLatestStatus(out StatusMessage status)
        {
            lock (dataLock)
            {
                status = latestStatus;
                return status != null;
            }
        }

        private async Task ConnectionLoopAsync(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                TcpClient currentClient = null;
                try
                {
                    currentClient = new TcpClient();
                    await currentClient.ConnectAsync(host, port).ConfigureAwait(false);
                    NetworkStream stream = currentClient.GetStream();
                    using (var reader = new StreamReader(stream))
                    using (var currentWriter = new StreamWriter(stream) { AutoFlush = true })
                    {
                        lock (dataLock)
                        {
                            tcpClient = currentClient;
                            writer = currentWriter;
                            connectionState = "CONNECTED";
                            lastError = string.Empty;
                        }

                        while (!token.IsCancellationRequested)
                        {
                            string line = await reader.ReadLineAsync().ConfigureAwait(false);
                            if (line == null)
                            {
                                break;
                            }

                            HandleServerLine(line);
                        }
                    }
                }
                catch (Exception exception) when (!(exception is OperationCanceledException))
                {
                    SetError(exception.Message);
                }
                finally
                {
                    lock (dataLock)
                    {
                        if (ReferenceEquals(tcpClient, currentClient))
                        {
                            tcpClient = null;
                            writer = null;
                        }
                        if (!token.IsCancellationRequested)
                        {
                            connectionState = "DISCONNECTED";
                        }
                    }
                    currentClient?.Close();
                }

                if (!autoReconnect || token.IsCancellationRequested)
                {
                    break;
                }

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(reconnectDelaySeconds), token)
                        .ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
            }

            SetConnectionState("DISCONNECTED");
        }

        private void HandleServerLine(string line)
        {
            ReceivedLine?.Invoke(line);
            try
            {
                var envelope = JsonUtility.FromJson<MessageEnvelope>(line);
                if (envelope == null || string.IsNullOrEmpty(envelope.type))
                {
                    SetError("Received JSON without message type");
                    return;
                }

                switch (envelope.type)
                {
                    case "status":
                        lock (dataLock)
                        {
                            latestStatus = JsonUtility.FromJson<StatusMessage>(line);
                        }
                        break;
                    case "brain_frame":
                        HandleBrainFrame(JsonUtility.FromJson<BrainFrame>(line));
                        break;
                    case "error":
                        var error = JsonUtility.FromJson<ErrorMessage>(line);
                        SetError(error == null ? "Brain server error" : error.error + ": " + error.message);
                        break;
                    case "ack":
                        break;
                    default:
                        SetError("Unknown server message type: " + envelope.type);
                        break;
                }
            }
            catch (Exception exception)
            {
                SetError("Protocol parse error: " + exception.Message);
            }
        }

        private void HandleBrainFrame(BrainFrame frame)
        {
            if (frame == null)
            {
                SetError("Received empty BrainFrame");
                return;
            }

            lock (dataLock)
            {
                latestBrainFrame = frame;
                latestFrameTicks = Stopwatch.GetTimestamp();
                if (frame.appliedRequestId > 0 && pendingRequestTicks.TryGetValue(frame.appliedRequestId, out long sentTicks))
                {
                    latestLatencyMs = (Stopwatch.GetTimestamp() - sentTicks) * 1000.0 / Stopwatch.Frequency;
                    pendingRequestTicks.Remove(frame.appliedRequestId);
                }
            }
        }

        private async Task SendCommandAsync(SetActionCommand command, int requestId)
        {
            StreamWriter currentWriter;
            lock (dataLock)
            {
                currentWriter = writer;
            }

            if (currentWriter == null)
            {
                return;
            }

            try
            {
                await sendLock.WaitAsync().ConfigureAwait(false);
                try
                {
                    string json = JsonUtility.ToJson(command);
                    SentLine?.Invoke(json);
                    await currentWriter.WriteLineAsync(json).ConfigureAwait(false);
                    await currentWriter.FlushAsync().ConfigureAwait(false);
                }
                finally
                {
                    sendLock.Release();
                }
            }
            catch (Exception exception) when (!(exception is OperationCanceledException))
            {
                SetError("Send failed for request " + requestId + ": " + exception.Message);
            }
        }

        private static bool IsAllowedAction(string action)
        {
            return action == "STOP" || action == "FORWARD" || action == "TURN_R" ||
                   action == "TURN_L" || action == "FORWARD_R" || action == "FORWARD_L";
        }

        private void SetConnectionState(string state)
        {
            lock (dataLock)
            {
                connectionState = state;
            }
        }

        private void SetError(string error)
        {
            lock (dataLock)
            {
                lastError = error ?? string.Empty;
            }
        }

        private void CloseSocket()
        {
            lock (dataLock)
            {
                writer = null;
                tcpClient?.Close();
                tcpClient = null;
            }
        }

        private void OnDestroy()
        {
            Disconnect();
            sendLock.Dispose();
        }
    }
}
