using System;
using System.Collections;
using System.IO;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Networking;

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
        bool previousRunInBackground;
        bool backgroundOwned;
        bool reportedFailure;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
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
                var component = root.AddComponent<UnityVideoPublisher>();
                component.settings = config;
                component.token = secret;
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
                byte[] jpeg;
                try { jpeg = Capture(); }
                catch (Exception)
                {
                    Debug.LogError("VIDEO_CAPTURE_FAILED");
                    enabled = false;
                    yield break;
                }
                nextCapture = Time.realtimeSinceStartupAsDouble + 1.0 / settings.framesPerSecond;
                upload = new UnityWebRequest(framesUrl, "POST");
                upload.uploadHandler = new UploadHandlerRaw(jpeg);
                upload.downloadHandler = new DownloadHandlerBuffer();
                upload.timeout = settings.requestTimeoutSeconds;
                upload.redirectLimit = 0;
                upload.SetRequestHeader("Content-Type", "image/jpeg");
                upload.SetRequestHeader("Authorization", "Bearer " + token);
                upload.SetRequestHeader("X-Publisher-Id", publisherId);
                upload.SetRequestHeader("X-Frame-Sequence", (sequence++).ToString(System.Globalization.CultureInfo.InvariantCulture));
                upload.SetRequestHeader("X-Execution-Os", executionOs);
                upload.SetRequestHeader("X-Source-Label", settings.label);
                // Only one frame in flight. Capture again after completion, never replay this JPEG.
                yield return upload.SendWebRequest();
                bool success = upload.result == UnityWebRequest.Result.Success;
                long status = upload.responseCode;
                upload.Dispose();
                upload = null;
                if (!success)
                {
                    if (!reportedFailure) Debug.LogWarning("VIDEO_UPLOAD_FAILED: HTTP " + status);
                    reportedFailure = true;
                    if (status == 401 || status == 403 || status == 404 || status == 409)
                    {
                        Debug.LogError("VIDEO_PUBLISHER_STOPPED: verify endpoint, token and stream ownership before restarting Play.");
                        enabled = false;
                        yield break;
                    }
                    yield return new WaitForSecondsRealtime(1);
                }
                else if (reportedFailure)
                {
                    Debug.Log("VIDEO_UPLOAD_RECOVERED");
                    reportedFailure = false;
                }
            }
        }

        byte[] Capture()
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
                ScreenCapture.CaptureScreenshotIntoRenderTexture(fullSize);
                bool flip = settings.verticalFlip == "on" ||
                    (settings.verticalFlip == "auto" && SystemInfo.graphicsUVStartsAtTop);
                Graphics.Blit(fullSize, scaled, new Vector2(1, flip ? -1 : 1), new Vector2(0, flip ? 1 : 0));
                RenderTexture.active = scaled;
                pixels.ReadPixels(new Rect(0, 0, scaled.width, scaled.height), 0, 0, false);
                pixels.Apply(false, false);
                return pixels.EncodeToJPG(settings.jpegQuality);
            }
            finally { RenderTexture.active = previous; }
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
            ReleaseTextures();
            token = null;
            if (backgroundOwned) { Application.runInBackground = previousRunInBackground; backgroundOwned = false; }
        }
    }
}
