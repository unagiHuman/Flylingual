using System;
using System.Collections;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Networking;
using Stopwatch = System.Diagnostics.Stopwatch;

namespace Flylingual.Video
{
    /// <summary>Opt-in final game framebuffer capture. Does not drive or read Brain/motor state.</summary>
    public sealed class UnityVideoPublisher : MonoBehaviour
    {
        [Serializable]
        public sealed class Settings
        {
            public bool enabled;
            public string endpoint = "http://127.0.0.1:8880";
            public string streamId = "unity-mac";
            public string tokenFile = "publish-token.txt";
            public string label = "Unity Game";
            public int width = 960;
            public int height = 540;
            public int framesPerSecond = 15;
            public int jpegQuality = 75;
            public int requestTimeoutSeconds = 3;
            public string verticalFlip = "auto";
            public bool diagnosticsOverlay = false;
        }

        Settings settings;
        string token;
        string publisherId;
        string executionOs;
        string framesUrl;
        long sequence;
        UnityWebRequest upload;
        RenderTexture fullSize;
        RenderTexture scaled;
        Texture2D pixels;
        UnityVideoBrainIdentity brainIdentity;
        Color[] markerColors;
        uint markerColorsNonce;
        uint probeNonce;
        long rateStartTicks;
        int updateFrames;
        int acceptedFrames;
        double gameFps;
        double videoFps;
        double previousUploadMs;
        float publisherBusyRetrySeconds;
        bool previousRunInBackground;
        bool backgroundOwned;
        bool reportedFailure;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled) return;
            if (FindAnyObjectByType<UnityVideoPublisher>() != null) return;
            string path = Environment.GetEnvironmentVariable("FLY_VIDEO_CONFIG");
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-flyVideoConfig") path = args[i + 1];
            if (string.IsNullOrEmpty(path))
            {
#if UNITY_EDITOR
                path = Path.GetFullPath(Path.Combine(Application.dataPath, "../../Runtime/Video/local/publisher.json"));
#else
                path = Path.Combine(Application.persistentDataPath, "fly-video.json");
#endif
            }
            if (!Path.IsPathRooted(path))
            {
                Debug.LogError("VIDEO_CONFIG_INVALID: use an absolute config path.");
                return;
            }
            if (!File.Exists(path)) return;
            try
            {
                var config = JsonUtility.FromJson<Settings>(File.ReadAllText(path));
                if (config == null || !config.enabled) return;
                string secret = Environment.GetEnvironmentVariable("FLY_VIDEO_PUBLISH_TOKEN");
                if (string.IsNullOrEmpty(secret))
                    secret = File.ReadAllText(Path.IsPathRooted(config.tokenFile) ? config.tokenFile :
                        Path.Combine(Path.GetDirectoryName(path), config.tokenFile)).Trim();
                Validate(config, secret);
                var root = new GameObject("Unity Video Publisher (runtime)");
                DontDestroyOnLoad(root);
                var identity = root.AddComponent<UnityVideoBrainIdentity>();
                var component = root.AddComponent<UnityVideoPublisher>();
                component.settings = config;
                component.token = secret;
                component.brainIdentity = identity;
                identity.Initialize();
            }
            catch (Exception)
            {
                // Paths, credentials and exception payloads are intentionally excluded.
                Debug.LogError("VIDEO_CONFIG_INVALID: check the local video settings and token file.");
            }
        }

        static void Validate(Settings config, string secret)
        {
            if (!Uri.TryCreate(config.endpoint, UriKind.Absolute, out var endpoint) ||
                (endpoint.Scheme != "http" && endpoint.Scheme != "https") ||
                (endpoint.Host != "127.0.0.1" && endpoint.Host != "localhost" && endpoint.Host != "[::1]") ||
                endpoint.AbsolutePath != "/" || endpoint.UserInfo.Length != 0 ||
                endpoint.Query.Length != 0 || endpoint.Fragment.Length != 0 ||
                !Regex.IsMatch(config.streamId ?? "", "^[a-z0-9-]{1,40}$") ||
                config.width < 16 || config.width > 1920 || config.width % 2 != 0 ||
                config.height < 16 || config.height > 1080 || config.height % 2 != 0 ||
                config.framesPerSecond < 1 || config.framesPerSecond > 30 ||
                config.jpegQuality < 1 || config.jpegQuality > 95 ||
                config.requestTimeoutSeconds < 1 || config.requestTimeoutSeconds > 10 ||
                (config.verticalFlip != "auto" && config.verticalFlip != "on" && config.verticalFlip != "off") ||
                !Regex.IsMatch(config.label ?? "", "^[ -~]{1,80}$") ||
                !Regex.IsMatch(secret ?? "", "^[ -~]{32,256}$"))
                throw new ArgumentException("Invalid video settings");
        }

        IEnumerator Start()
        {
            if (settings == null) { enabled = false; yield break; }
            if (SystemInfo.graphicsDeviceType == UnityEngine.Rendering.GraphicsDeviceType.Null)
            {
                Debug.LogError("VIDEO_CAPTURE_UNAVAILABLE: a graphics device is required.");
                enabled = false;
                yield break;
            }
            executionOs = Application.platform == RuntimePlatform.OSXEditor || Application.platform == RuntimePlatform.OSXPlayer
                ? "macOS" : (Application.platform == RuntimePlatform.WindowsEditor || Application.platform == RuntimePlatform.WindowsPlayer
                    ? "Windows" : "unsupported");
            if (executionOs == "unsupported") { enabled = false; yield break; }
            publisherId = Guid.NewGuid().ToString("N");
            framesUrl = settings.endpoint.TrimEnd('/') + "/api/video/streams/" + settings.streamId + "/frames";
            rateStartTicks = Stopwatch.GetTimestamp();
            previousRunInBackground = Application.runInBackground;
            Application.runInBackground = true;
            backgroundOwned = true;
            var endOfFrame = new WaitForEndOfFrame();
            double nextCapture = 0;
            Debug.Log("VIDEO_PUBLISHER_STARTED: " + settings.streamId + " " + executionOs);
            while (enabled)
            {
                yield return endOfFrame;
                if (Time.realtimeSinceStartupAsDouble < nextCapture || Screen.width < 16 || Screen.height < 16) continue;
                CaptureResult capture;
                try { capture = Capture(); }
                catch (Exception)
                {
                    Debug.LogError("VIDEO_CAPTURE_FAILED");
                    enabled = false;
                    yield break;
                }
                nextCapture = Time.realtimeSinceStartupAsDouble + 1.0 / settings.framesPerSecond;
                upload = new UnityWebRequest(framesUrl, "POST");
                upload.uploadHandler = new UploadHandlerRaw(capture.jpeg);
                upload.downloadHandler = new DownloadHandlerBuffer();
                upload.timeout = settings.requestTimeoutSeconds;
                upload.redirectLimit = 0;
                upload.SetRequestHeader("Content-Type", "image/jpeg");
                upload.SetRequestHeader("Authorization", "Bearer " + token);
                upload.SetRequestHeader("X-Publisher-Id", publisherId);
                upload.SetRequestHeader("X-Frame-Sequence", (sequence++).ToString(System.Globalization.CultureInfo.InvariantCulture));
                upload.SetRequestHeader("X-Execution-Os", executionOs);
                upload.SetRequestHeader("X-Source-Label", settings.label);
                upload.SetRequestHeader("X-Frame-Metadata", BuildFrameMetadata(capture));
                // Only one frame in flight. Capture again after completion, never replay this JPEG.
                long uploadStarted = Stopwatch.GetTimestamp();
                yield return upload.SendWebRequest();
                previousUploadMs = Math.Max(0, (Stopwatch.GetTimestamp() - uploadStarted) * 1000.0 / Stopwatch.Frequency);
                bool success = upload.result == UnityWebRequest.Result.Success;
                long status = upload.responseCode;
                string response = upload.downloadHandler == null ? string.Empty : upload.downloadHandler.text;
                upload.Dispose();
                upload = null;
                if (!success)
                {
                    string error = ReadErrorCode(response);
                    if (status == 409 && error == "publisher_slot_in_use")
                    {
                        publisherBusyRetrySeconds = Mathf.Min(5f, publisherBusyRetrySeconds <= 0f ? 0.25f : publisherBusyRetrySeconds * 2f);
                        yield return new WaitForSecondsRealtime(publisherBusyRetrySeconds);
                        continue;
                    }
                    if (!reportedFailure) Debug.LogWarning("VIDEO_UPLOAD_FAILED: HTTP " + status);
                    reportedFailure = true;
                    if (status == 401 || status == 403 || status == 404)
                    {
                        Debug.LogError("VIDEO_PUBLISHER_STOPPED: verify endpoint, token and stream ownership before restarting Play.");
                        enabled = false;
                        yield break;
                    }
                    if (status == 409 && error == "old_frame_sequence")
                    {
                        Debug.LogError("VIDEO_PUBLISHER_STOPPED: frame sequence was rejected.");
                        enabled = false;
                        yield break;
                    }
                    if (status == 409)
                    {
                        Debug.LogError("VIDEO_PUBLISHER_STOPPED: stream ownership was rejected.");
                        enabled = false;
                        yield break;
                    }
                    yield return new WaitForSecondsRealtime(1);
                }
                else
                {
                    publisherBusyRetrySeconds = 0f;
                    acceptedFrames++;
                    if (TryReadUploadResponse(response, out uint acceptedNonce)) probeNonce = acceptedNonce;
                    else if (!reportedFailure) Debug.LogWarning("VIDEO_UPLOAD_RESPONSE_INVALID");
                    if (reportedFailure)
                    {
                        Debug.Log("VIDEO_UPLOAD_RECOVERED");
                        reportedFailure = false;
                    }
                }
            }
        }

        void Update()
        {
            if (settings == null) return;
            updateFrames++;
            long now = Stopwatch.GetTimestamp();
            double elapsed = (now - rateStartTicks) / (double)Stopwatch.Frequency;
            if (elapsed < 1.0) return;
            gameFps = Math.Min(10000.0, updateFrames / elapsed);
            videoFps = Math.Min(10000.0, acceptedFrames / elapsed);
            updateFrames = 0;
            acceptedFrames = 0;
            rateStartTicks = now;
        }

        CaptureResult Capture()
        {
            if (fullSize == null || fullSize.width != Screen.width || fullSize.height != Screen.height)
            {
                ReleaseTextures();
                fullSize = new RenderTexture(Screen.width, Screen.height, 0, RenderTextureFormat.ARGB32);
                fullSize.Create();
                // Preserve aspect ratio, with even output dimensions for video encoders.
                float scale = Mathf.Min((float)settings.width / Screen.width, (float)settings.height / Screen.height);
                int width = Mathf.Max(16, (Mathf.FloorToInt(Screen.width * scale) / 2) * 2);
                int height = Mathf.Max(16, (Mathf.FloorToInt(Screen.height * scale) / 2) * 2);
                scaled = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32);
                scaled.Create();
                pixels = new Texture2D(width, height, TextureFormat.RGB24, false);
            }
            var previous = RenderTexture.active;
            try
            {
                long captureStarted = Stopwatch.GetTimestamp();
                ScreenCapture.CaptureScreenshotIntoRenderTexture(fullSize);
                bool flip = settings.verticalFlip == "on" ||
                    (settings.verticalFlip == "auto" && SystemInfo.graphicsUVStartsAtTop);
                Graphics.Blit(fullSize, scaled, new Vector2(1, flip ? -1 : 1), new Vector2(0, flip ? 1 : 0));
                RenderTexture.active = scaled;
                pixels.ReadPixels(new Rect(0, 0, scaled.width, scaled.height), 0, 0, false);
                bool markerEnabled = settings.diagnosticsOverlay && pixels.width >= 256 && pixels.height >= 8;
                if (markerEnabled && probeNonce != 0) DrawMarker(probeNonce);
                pixels.Apply(false, false);
                double captureMs = Math.Max(0, (Stopwatch.GetTimestamp() - captureStarted) * 1000.0 / Stopwatch.Frequency);
                long encodeStarted = Stopwatch.GetTimestamp();
                byte[] jpeg = pixels.EncodeToJPG(settings.jpegQuality);
                double encodeMs = Math.Max(0, (Stopwatch.GetTimestamp() - encodeStarted) * 1000.0 / Stopwatch.Frequency);
                return new CaptureResult { jpeg = jpeg, captureMs = captureMs, encodeMs = encodeMs, markerEnabled = markerEnabled };
            }
            finally { RenderTexture.active = previous; }
        }

        string BuildFrameMetadata(CaptureResult capture)
        {
            var metadata = new FrameMetadata
            {
                captureMs = capture.captureMs,
                encodeMs = capture.encodeMs,
                uploadMs = previousUploadMs,
                gameFps = gameFps,
                videoFps = videoFps,
                jpegBytes = capture.jpeg == null ? 0 : capture.jpeg.Length,
                diagnosticsOverlay = capture.markerEnabled,
            };
            UnityVideoBrainIdentity.SnapshotData identity = brainIdentity == null ? null : brainIdentity.Snapshot();
            // The receiver accepts brainIdentity only as a complete provenance
            // record.  While the passive observer has no verified binding, omit
            // the optional key instead of serializing an empty identity object.
            string json = identity == null ? JsonUtility.ToJson(metadata) : JsonUtility.ToJson(new FrameMetadataWithIdentity
            {
                captureMs = metadata.captureMs, encodeMs = metadata.encodeMs, uploadMs = metadata.uploadMs,
                gameFps = metadata.gameFps, videoFps = metadata.videoFps, jpegBytes = metadata.jpegBytes,
                diagnosticsOverlay = metadata.diagnosticsOverlay, brainIdentity = identity,
            });
            return Convert.ToBase64String(Encoding.UTF8.GetBytes(json));
        }

        void DrawMarker(uint nonce)
        {
            if (markerColors == null || markerColorsNonce != nonce)
            {
                markerColors = new Color[256 * 8];
                markerColorsNonce = nonce;
                ulong bits = ((ulong)0xD3A5 << 48) | ((ulong)nonce << 16) |
                    (ushort)(((nonce >> 16) ^ (nonce & 0xffff) ^ 0x6B4D) & 0xffff);
                for (int bit = 0; bit < 64; bit++)
                {
                    bool one = ((bits >> (63 - bit)) & 1UL) != 0;
                    Color color = one ? Color.white : Color.black;
                    for (int y = 0; y < 8; y++)
                        for (int x = 0; x < 4; x++) markerColors[y * 256 + bit * 4 + x] = color;
                }
            }
            pixels.SetPixels(0, 0, 256, 8, markerColors);
        }

        [Serializable] sealed class FrameMetadata
        {
            public double captureMs, encodeMs, uploadMs, gameFps, videoFps;
            public int jpegBytes;
            public bool diagnosticsOverlay;
        }
        [Serializable] sealed class FrameMetadataWithIdentity
        {
            public double captureMs, encodeMs, uploadMs, gameFps, videoFps;
            public int jpegBytes;
            public bool diagnosticsOverlay;
            public UnityVideoBrainIdentity.SnapshotData brainIdentity;
        }
        [Serializable] sealed class UploadResponse { public long acceptedSequence; public uint probeNonce; }
        [Serializable] sealed class ErrorResponse { public string error; }
        sealed class CaptureResult { public byte[] jpeg; public double captureMs, encodeMs; public bool markerEnabled; }

        static bool TryReadUploadResponse(string response, out uint nonce)
        {
            nonce = 0;
            if (string.IsNullOrEmpty(response) || response.Length > 256) return false;
            try { nonce = JsonUtility.FromJson<UploadResponse>(response).probeNonce; return true; }
            catch (Exception) { return false; }
        }

        static string ReadErrorCode(string response)
        {
            if (string.IsNullOrEmpty(response) || response.Length > 256) return string.Empty;
            try { return JsonUtility.FromJson<ErrorResponse>(response)?.error ?? string.Empty; }
            catch (Exception) { return string.Empty; }
        }

        void ReleaseTextures()
        {
            if (fullSize != null) { fullSize.Release(); Destroy(fullSize); fullSize = null; }
            if (scaled != null) { scaled.Release(); Destroy(scaled); scaled = null; }
            if (pixels != null) { Destroy(pixels); pixels = null; }
        }

        void OnDisable()
        {
            StopAllCoroutines();
            if (upload != null) { upload.Abort(); upload.Dispose(); upload = null; }
            if (brainIdentity != null) { brainIdentity.enabled = false; Destroy(brainIdentity); brainIdentity = null; }
            ReleaseTextures();
            token = null;
            if (backgroundOwned) { Application.runInBackground = previousRunInBackground; backgroundOwned = false; }
        }

        void OnEnable()
        {
            // Disabled publishers discard credentials and require a fresh Play/Player launch.
            if (settings != null && string.IsNullOrEmpty(token)) { enabled = false; return; }
            if (settings != null && brainIdentity == null)
            {
                brainIdentity = gameObject.AddComponent<UnityVideoBrainIdentity>();
                brainIdentity.Initialize();
            }
        }
    }
}
