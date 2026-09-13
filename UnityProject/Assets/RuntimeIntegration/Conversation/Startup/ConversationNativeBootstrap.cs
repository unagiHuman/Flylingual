using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Starts the Windows-local Bridge only when -flyConversation is present.</summary>
    [DefaultExecutionOrder(-10000)]
    public sealed class ConversationNativeBootstrap : MonoBehaviour
    {
        private static ConversationNativeBootstrap instance;
        [Serializable]
        private sealed class NativeLaunchConfig { public string bridgePython; }

        [Serializable]
        private sealed class NativeStatus { public string state; public string endpoint; public string message; }

        private const string RepoRootFlag = "-flyRepoRoot";
        private const float StartupTimeoutSeconds = 50f;
        private string statusPath;
        private string stopPath;
        private string heartbeatPath;
        private Process helperProcess;
        private CancellationTokenSource lifetime;
        private bool running;
        private bool closing;
        private string visibleStatus;
        private float nextHeartbeat;
        public string RunDirectory { get; private set; }
        public string StatusPath => statusPath;
        public string StartupError { get; private set; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void CreateForCommandLine()
        {
            if (!NativeConversationRuntime.Requested || FindFirstObjectByType<ConversationNativeBootstrap>() != null) return;
            new GameObject("ConversationNativeBootstrap").AddComponent<ConversationNativeBootstrap>();
        }

        private void Awake()
        {
            if (instance != null && instance != this) { Destroy(gameObject); return; }
            instance = this;
#if UNITY_EDITOR
            // An explicitly added test-scene component opts that Editor scene in.
            NativeConversationRuntime.SceneOptIn = true;
#endif
        }

        private async void Start()
        {
            if (instance != this) return;
#if UNITY_EDITOR
            if (!NativeConversationRuntime.Requested && !NativeConversationRuntime.SceneOptIn) { enabled = false; return; }
#else
            if (!NativeConversationRuntime.Requested) { enabled = false; return; }
#endif
            DontDestroyOnLoad(gameObject);
            lifetime = new CancellationTokenSource();
            try
            {
                string root = ResolveRepositoryRoot();
                string configPath = Path.Combine(root, "Runtime", "Config", "windows-native.local.json");
                if (!File.Exists(configPath)) configPath = Path.Combine(root, "Runtime", "Config", "windows-stack.local.json");
                if (!File.Exists(configPath)) throw new InvalidOperationException("A local windows-native or windows-stack configuration was not found.");
                NativeLaunchConfig config = JsonUtility.FromJson<NativeLaunchConfig>(File.ReadAllText(configPath));
                if (config == null || String.IsNullOrWhiteSpace(config.bridgePython))
                    throw new InvalidOperationException("windows-native configuration has no bridgePython.");

                RunDirectory = Path.Combine(root, "artifacts", "windows-native-runs", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(RunDirectory);
                statusPath = Path.Combine(RunDirectory, "status.json");
                stopPath = Path.Combine(RunDirectory, "stop");
                heartbeatPath = Path.Combine(RunDirectory, "heartbeat");
                File.WriteAllText(heartbeatPath, String.Empty);
                visibleStatus = "Starting local conversation services…";
                StartHelper(root, configPath, config.bridgePython);
                await WaitForServiceAsync(lifetime.Token);
            }
            catch (OperationCanceledException) when (closing) { }
            catch (Exception exception)
            {
                running = false;
                StartupError = exception.Message;
                visibleStatus = "Conversation service failed: " + exception.Message;
                UnityEngine.Debug.LogError(visibleStatus, this);
                Close();
            }
        }

        private void Update()
        {
            if (closing || String.IsNullOrEmpty(heartbeatPath) || Time.unscaledTime < nextHeartbeat) return;
            nextHeartbeat = Time.unscaledTime + 1f;
            try { File.SetLastWriteTimeUtc(heartbeatPath, DateTime.UtcNow); }
            catch (Exception exception) { Fail("heartbeat failed: " + exception.Message); }
        }

        private void OnApplicationQuit() { Close(); }
        private void OnDisable() { Close(); }
        private void OnDestroy()
        {
            if (instance != this) return;
            instance = null;
#if UNITY_EDITOR
            NativeConversationRuntime.SceneOptIn = false;
#endif
            Close();
        }

        private void OnGUI()
        {
            if (Flylingual.PlayScreen.PlayScreenRuntime.Active || running || String.IsNullOrEmpty(visibleStatus)) return;
            GUI.Box(new Rect(14, Math.Max(14, Screen.height - 64), Math.Min(Screen.width - 28, 760), 48), visibleStatus);
        }

        private void StartHelper(string root, string configPath, string configuredPython)
        {
            string python = Path.IsPathRooted(configuredPython) ? configuredPython : Path.Combine(root, configuredPython);
            string helper = Path.Combine(root, "tools", "windows_native.py");
            if (!File.Exists(python) || !File.Exists(helper)) throw new InvalidOperationException("native launcher prerequisites were not found.");
            Process current = Process.GetCurrentProcess();
            double created = new DateTimeOffset(current.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0;
            ProcessStartInfo info = new ProcessStartInfo {
                FileName = python,
                Arguments = Quote(helper) + " --config " + Quote(configPath) + " --status " + Quote(statusPath)
                    + " --stop " + Quote(stopPath) + " --heartbeat " + Quote(heartbeatPath)
                    + " --owner-pid " + current.Id.ToString(CultureInfo.InvariantCulture)
                    + " --owner-created " + created.ToString("R", CultureInfo.InvariantCulture),
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
            ScrubChildEnvironment(info);
            helperProcess = Process.Start(info);
            if (helperProcess == null) throw new InvalidOperationException("native helper could not be started.");
        }

        private async Task WaitForServiceAsync(CancellationToken cancellation)
        {
            float deadline = Time.realtimeSinceStartup + StartupTimeoutSeconds;
            while (Time.realtimeSinceStartup < deadline)
            {
                cancellation.ThrowIfCancellationRequested();
                if (helperProcess == null || helperProcess.HasExited) throw new InvalidOperationException("local conversation helper exited during startup.");
                NativeStatus status = ReadStatus();
                if (status != null && status.state == "ready" && !String.IsNullOrWhiteSpace(status.endpoint))
                {
                    running = true;
                    visibleStatus = "Local conversation service connected.";
                    ConversationSessionController controller = FindFirstObjectByType<ConversationSessionController>();
                    if (controller == null) controller = gameObject.AddComponent<ConversationSessionController>();
                    if (FindFirstObjectByType<ConversationView>() == null) gameObject.AddComponent<ConversationView>();
                    await controller.ConnectAsync(status.endpoint);
                    cancellation.ThrowIfCancellationRequested();
                    _ = MonitorHelperAsync(cancellation);
                    return;
                }
                if (status != null && status.state == "failed") throw new InvalidOperationException(status.message ?? "unknown helper failure");
                await Task.Delay(150, cancellation);
            }
            throw new TimeoutException("local conversation service did not become ready.");
        }

        private async Task MonitorHelperAsync(CancellationToken cancellation)
        {
            try
            {
                while (!cancellation.IsCancellationRequested)
                {
                    if (helperProcess == null || helperProcess.HasExited) { Fail("local conversation helper exited."); return; }
                    NativeStatus status = ReadStatus();
                    if (status != null && (status.state == "failed" || status.state == "stopped"))
                    {
                        Fail(status.message ?? "local conversation service stopped.");
                        return;
                    }
                    await Task.Delay(250, cancellation);
                }
            }
            catch (OperationCanceledException) { }
        }

        private NativeStatus ReadStatus()
        {
            try { return File.Exists(statusPath) ? JsonUtility.FromJson<NativeStatus>(File.ReadAllText(statusPath)) : null; }
            catch (IOException) { return null; }
            catch (ArgumentException) { return null; }
        }

        private void Close()
        {
            if (closing) return;
            closing = true;
            lifetime?.Cancel();
            RequestStop();
        }

        private void RequestStop()
        {
            if (String.IsNullOrEmpty(stopPath)) return;
            try { File.WriteAllText(stopPath, "stop"); }
            catch (Exception) { /* Application shutdown cannot recover from an unavailable local folder. */ }
            running = false;
        }

        private void Fail(string message)
        {
            if (closing) return;
            StartupError = message;
            running = false;
            visibleStatus = "Conversation service failed: " + message;
            Close();
        }

        private static void ScrubChildEnvironment(ProcessStartInfo info)
        {
            List<string> names = new List<string>();
            foreach (string name in info.EnvironmentVariables.Keys) if (Sensitive(name)) names.Add(name);
            foreach (string name in names) info.EnvironmentVariables.Remove(name);
        }

        private static bool Sensitive(string name)
        {
            string upper = name.ToUpperInvariant();
            return upper.Contains("API_KEY") || upper.Contains("APIKEY") || upper.Contains("TOKEN") || upper.Contains("SECRET")
                || upper.Contains("PASSWORD") || upper.StartsWith("OPENAI_") || upper.StartsWith("ANTHROPIC_") || upper.StartsWith("AWS_");
        }

        private static string ArgumentValue(string flag)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int index = 0; index + 1 < arguments.Length; index++) if (arguments[index] == flag) return arguments[index + 1];
            return null;
        }

        private static string ResolveRepositoryRoot()
        {
            string supplied = ArgumentValue(RepoRootFlag);
            if (!String.IsNullOrWhiteSpace(supplied) && HasMarker(supplied)) return Path.GetFullPath(supplied);
            string[] starts = { Application.dataPath, AppDomain.CurrentDomain.BaseDirectory, Directory.GetCurrentDirectory() };
            foreach (string start in starts)
            {
                for (DirectoryInfo directory = new DirectoryInfo(start); directory != null; directory = directory.Parent)
                    if (HasMarker(directory.FullName)) return directory.FullName;
            }
            throw new DirectoryNotFoundException("Flylingual repository root was not found; pass -flyRepoRoot <path>.");
        }

        private static bool HasMarker(string path) => File.Exists(Path.Combine(path, "tools", "dev.py"));
        private static string Quote(string value) => "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
