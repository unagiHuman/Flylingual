using System;
using System.Collections.Generic;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Flylingual.Conversation
{
    /// <summary>Single, bounded local Bridge WebSocket. It deliberately exposes only safe error codes.</summary>
    public sealed class BridgeConversationSocket : IDisposable
    {
        public const int MaximumMessageBytes = 1024 * 1024;
        const int MaximumQueuedMessages = 64;
        readonly object gate = new object();
        readonly Queue<Func<string>> outbound = new Queue<Func<string>>();
        readonly SemaphoreSlim outboundSignal = new SemaphoreSlim(0);
        readonly CancellationTokenSource lifetime = new CancellationTokenSource();
        ClientWebSocket socket;
        Task receiveTask;
        Task sendTask;
        bool disposed;

        public event Action<string> Message;
        public event Action<string> Closed;
        public event Action<string> Faulted;
        public bool IsConnected => socket != null && socket.State == WebSocketState.Open;
        public int QueueDepth { get { lock (gate) return outbound.Count; } }

        public static bool TryValidateLoopbackUrl(string value, out Uri uri, out string error)
        {
            uri = null;
            error = null;
            if (!Uri.TryCreate(value, UriKind.Absolute, out var candidate) || candidate.Scheme != "ws")
            {
                error = "invalid_control_url";
                return false;
            }
            if (!string.IsNullOrEmpty(candidate.UserInfo) || !string.IsNullOrEmpty(candidate.Query)
                || !string.IsNullOrEmpty(candidate.Fragment) || candidate.AbsolutePath != "/ws")
            {
                error = "invalid_control_url";
                return false;
            }
            if (!string.Equals(candidate.Host, "localhost", StringComparison.OrdinalIgnoreCase)
                && (!IPAddress.TryParse(candidate.Host, out var address) || !IPAddress.IsLoopback(address)))
            {
                error = "control_url_not_loopback";
                return false;
            }
            uri = candidate;
            return true;
        }

        public async Task ConnectAsync(string url, CancellationToken cancellationToken = default(CancellationToken))
        {
            if (disposed) throw new ObjectDisposedException(nameof(BridgeConversationSocket));
            if (!TryValidateLoopbackUrl(url, out var endpoint, out var validationError))
                throw new ConversationTransportException(validationError);
            if (socket != null) throw new ConversationTransportException("control_socket_already_created");

            socket = new ClientWebSocket();
            using (var combined = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token, cancellationToken))
            {
                try { await socket.ConnectAsync(endpoint, combined.Token).ConfigureAwait(false); }
                catch (OperationCanceledException) { throw; }
                catch (WebSocketException) { DisposeSocket(); throw new ConversationTransportException("control_connect_failed"); }
                catch (Exception) { DisposeSocket(); throw new ConversationTransportException("control_connect_failed"); }
            }
            receiveTask = ReceiveLoopAsync(lifetime.Token);
            sendTask = SendLoopAsync(lifetime.Token);
        }

        public void Enqueue(string json)
        {
            if (disposed || !IsConnected) throw new ConversationTransportException("control_not_connected");
            if (string.IsNullOrEmpty(json) || Encoding.UTF8.GetByteCount(json) > MaximumMessageBytes)
                throw new ConversationTransportException("invalid_outbound_message");
            lock (gate)
            {
                if (outbound.Count >= MaximumQueuedMessages)
                    throw new ConversationTransportException("control_send_queue_full");
                outbound.Enqueue(() => json);
            }
            outboundSignal.Release();
        }

        // Monotonic sender-side age; never call Unity APIs from the send task.
        public void EnqueueFresh(string jsonWithAgeToken, float observedAgeMs)
        {
            if (disposed || !IsConnected) throw new ConversationTransportException("control_not_connected");
            if (string.IsNullOrEmpty(jsonWithAgeToken) || Encoding.UTF8.GetByteCount(jsonWithAgeToken) > MaximumMessageBytes
                || float.IsNaN(observedAgeMs) || observedAgeMs < 0 || observedAgeMs > 750)
                throw new ConversationTransportException("invalid_outbound_message");
            long queuedAt = System.Diagnostics.Stopwatch.GetTimestamp();
            lock (gate)
            {
                if (outbound.Count >= MaximumQueuedMessages) throw new ConversationTransportException("control_send_queue_full");
                outbound.Enqueue(() => {
                    double age = observedAgeMs + (System.Diagnostics.Stopwatch.GetTimestamp() - queuedAt) * 1000d / System.Diagnostics.Stopwatch.Frequency;
                    return age > 750 ? null : jsonWithAgeToken.Replace("__OBSERVATION_AGE__", age.ToString("F3", System.Globalization.CultureInfo.InvariantCulture));
                });
            }
            outboundSignal.Release();
        }

        async Task SendLoopAsync(CancellationToken cancellationToken)
        {
            try
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    await outboundSignal.WaitAsync(cancellationToken).ConfigureAwait(false);
                    Func<string> pending;
                    lock (gate) pending = outbound.Count == 0 ? null : outbound.Dequeue();
                    string message = pending?.Invoke();
                    if (message == null) continue;
                    var bytes = Encoding.UTF8.GetBytes(message);
                    await socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, cancellationToken).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException) { }
            catch (WebSocketException) { NotifyFault("control_send_failed"); }
            catch (Exception) { NotifyFault("control_send_failed"); }
        }

        async Task ReceiveLoopAsync(CancellationToken cancellationToken)
        {
            var buffer = new byte[8192];
            try
            {
                while (!cancellationToken.IsCancellationRequested && socket.State == WebSocketState.Open)
                {
                    var payload = new List<byte>(8192);
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), cancellationToken).ConfigureAwait(false);
                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            NotifyClosed("control_closed");
                            return;
                        }
                        if (result.MessageType != WebSocketMessageType.Text || payload.Count + result.Count > MaximumMessageBytes)
                        {
                            NotifyFault(result.MessageType == WebSocketMessageType.Text ? "control_message_too_large" : "control_invalid_frame");
                            await CloseAsync(WebSocketCloseStatus.MessageTooBig, cancellationToken).ConfigureAwait(false);
                            return;
                        }
                        for (var i = 0; i < result.Count; i++) payload.Add(buffer[i]);
                    } while (!result.EndOfMessage);
                    Message?.Invoke(Encoding.UTF8.GetString(payload.ToArray()));
                }
            }
            catch (OperationCanceledException) { }
            catch (WebSocketException) { NotifyFault("control_receive_failed"); }
            catch (Exception) { NotifyFault("control_receive_failed"); }
        }

        async Task CloseAsync(WebSocketCloseStatus status, CancellationToken cancellationToken)
        {
            if (socket != null && socket.State == WebSocketState.Open)
            {
                try { await socket.CloseOutputAsync(status, "closed", cancellationToken).ConfigureAwait(false); }
                catch (Exception) { }
            }
        }

        void NotifyFault(string code) { Faulted?.Invoke(code); }
        void NotifyClosed(string code) { Closed?.Invoke(code); }
        void DisposeSocket() { socket?.Dispose(); socket = null; }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            lifetime.Cancel();
            outboundSignal.Release();
            DisposeSocket();
            outboundSignal.Dispose();
            lifetime.Dispose();
        }
    }

    public sealed class ConversationTransportException : Exception
    {
        public ConversationTransportException(string code) : base(code) { Code = code; }
        public string Code { get; }
    }
}
