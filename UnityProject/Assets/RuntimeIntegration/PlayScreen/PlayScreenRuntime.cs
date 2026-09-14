using FlyBrainVisualization;
using Flylingual.Conversation;
using FlyVisualDemo;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.Rendering.Universal;

namespace Flylingual.PlayScreen
{
    /// <summary>Owns presentation only. Body control remains with the existing conversation safety gate.</summary>
    [DisallowMultipleComponent]
    public sealed class PlayScreenRuntime : MonoBehaviour
    {
        public Shader neuralShader;
        Camera gameCamera;
        RenderTexture gameTexture, previousTexture;
        Rect previousRect;
        float previousAspect;
        PlayScreenView view;
        NeuralVisualizationPanel neural;
        ConversationSessionController conversation;
        GameObject ownedNeural;
        Material ownedMaterial;
        bool configured;
        public static bool Active { get; private set; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            Active = false;
            SceneManager.sceneLoaded -= OnSceneLoaded;
            SceneManager.sceneLoaded += OnSceneLoaded;
        }

        static void OnSceneLoaded(Scene scene, LoadSceneMode mode) => InstallForNativePlayer();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void InstallForNativePlayer()
        {
            if (NativeConversationRuntime.Enabled && FindFirstObjectByType<PlayScreenRuntime>() == null)
                new GameObject("Flylingual Play Screen").AddComponent<PlayScreenRuntime>();
        }

        void Start()
        {
            var demo = FindFirstObjectByType<WindowsReplayDemo>();
            gameCamera = demo != null ? demo.view : Camera.main;
            if (gameCamera == null) { Debug.LogError("PLAY_SCREEN_NO_GAME_CAMERA"); enabled = false; return; }
            previousTexture = gameCamera.targetTexture; previousRect = gameCamera.rect; previousAspect = gameCamera.aspect;
            // Full 16:9 camera image, independently scaled by the UI. No FOV or crop change.
            gameTexture = new RenderTexture(1600, 900, 24, RenderTextureFormat.ARGB32) { name = "Flylingual Game View", antiAliasing = 1 };
            gameTexture.Create(); gameCamera.targetTexture = gameTexture;
            gameCamera.rect = new Rect(0, 0, 1, 1); gameCamera.aspect = 16f / 9f;
            neural = FindFirstObjectByType<NeuralVisualizationPanel>();
            if (neural == null) neural = CreateNeural();
            neural.SetEmbedded(true);
            view = GetComponent<PlayScreenView>() ?? gameObject.AddComponent<PlayScreenView>();
            view.Configure(gameTexture, neural);
            bool blindStage = FindAnyObjectByType<Flylingual.BlindSugarRun.BlindSugarRunSession>() != null;
            bool developerView = System.Array.IndexOf(System.Environment.GetCommandLineArgs(), "-blindSugarDeveloperView") >= 0;
            view.SetBlindMode(blindStage && !developerView);
            configured = Active = true;
            Debug.Log("PLAY_SCREEN_READY game=1600x900 layout=three-panel");
        }

        NeuralVisualizationPanel CreateNeural()
        {
            ownedNeural = new GameObject("Play Screen Neural Display"); ownedNeural.SetActive(false);
            ownedNeural.transform.SetParent(transform, false);
            var stage = new GameObject("Observation Stage"); stage.transform.SetParent(ownedNeural.transform, false);
            stage.transform.localPosition = new Vector3(0, -10000, 0); stage.layer = 31;
            var points = new GameObject("Observed Neurons"); points.transform.SetParent(stage.transform, false); points.layer = 31;
            var cloud = points.AddComponent<NeuralPointCloud>();
            if (neuralShader == null) neuralShader = Shader.Find("FlyBrain/Neural Point Cloud");
            if (neuralShader != null) { ownedMaterial = new Material(neuralShader); cloud.SetMaterial(ownedMaterial); }
            var cameraObject = new GameObject("Neural Camera"); cameraObject.transform.SetParent(stage.transform, false);
            cameraObject.transform.localPosition = new Vector3(0, 0, -4);
            var camera = cameraObject.AddComponent<Camera>();
            camera.orthographic = true; camera.orthographicSize = 1.25f; camera.nearClipPlane = .1f; camera.farClipPlane = 10;
            camera.cullingMask = 1 << 31; camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(.025f, .044f, .072f); camera.allowHDR = camera.allowMSAA = false;
            var urp = cameraObject.AddComponent<UniversalAdditionalCameraData>(); urp.renderPostProcessing = urp.renderShadows = false;
            var observer = ownedNeural.AddComponent<NeuralActivityObserver>();
            observer.Configure(null, Resources.Load<TextAsset>("BrainVisualization/malecns-atlas"), cloud);
            var panel = ownedNeural.AddComponent<NeuralVisualizationPanel>(); panel.Configure(observer, cloud, camera, points.transform);
            panel.SetEmbedded(true); ownedNeural.SetActive(true); return panel;
        }

        void Update()
        {
            if (!configured) return;
            if (conversation == null)
            {
                conversation = FindFirstObjectByType<ConversationSessionController>();
                if (conversation != null) neural.Observer.ConfigureConversation(conversation);
            }
        }

        void OnDisable()
        {
            if (!configured) return;
            configured = Active = false;
            if (gameCamera != null) { gameCamera.targetTexture = previousTexture; gameCamera.rect = previousRect; gameCamera.aspect = previousAspect; }
            if (neural != null) neural.SetEmbedded(false);
            if (view != null) Destroy(view);
            if (ownedNeural != null) Destroy(ownedNeural);
            if (ownedMaterial != null) Destroy(ownedMaterial);
            if (gameTexture != null) { gameTexture.Release(); Destroy(gameTexture); }
        }
    }
}
