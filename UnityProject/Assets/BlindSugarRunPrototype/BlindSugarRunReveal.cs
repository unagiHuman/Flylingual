using Flylingual.PlayScreen;
using Flylingual.Conversation;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Presentation after a confirmed goal. World bounds never enter the voice context.</summary>
    [DefaultExecutionOrder(32000)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunReveal : MonoBehaviour
    {
        const float FadeSeconds = .7f, PullBackSeconds = 3.5f, EndSeconds = 8f;
        BlindSugarRunSession stage;
        BlindSugarRunNarrator narrator;
        ConversationSessionController conversation;
        Camera worldCamera;
        RenderTexture texture, previousTexture;
        UIDocument document;
        PanelSettings settings;
        Font font;
        VisualElement shade;
        Label title;
        Button retry;
        Vector3 fromPosition, fromFocus, destination, focus;
        Quaternion fromRotation;
        float startedAt, previousFarClip;
        bool begun, stopped;
        public bool RevealStarted { get; private set; }
        public bool Complete { get; private set; }

        public void Begin(FlyBody fly, BlindSugarRunNarrator script, ConversationSessionController controller)
        {
            if (begun || fly == null) return;
            stage = GetComponent<BlindSugarRunSession>();
            if (stage == null || stage.State != BlindSugarRunSession.StageState.Goal) return;
            narrator = script; conversation = controller;
            var demo = FindAnyObjectByType<WindowsReplayDemo>();
            worldCamera = demo != null ? demo.view : Camera.main;
            begun = true; startedAt = Time.unscaledTime;
            fromFocus = fly.Position;
            if (worldCamera != null)
            {
                fromPosition = worldCamera.transform.position; fromRotation = worldCamera.transform.rotation;
                previousTexture = worldCamera.targetTexture; previousFarClip = worldCamera.farClipPlane;
                texture = new RenderTexture(1600, 900, 24) { name = "Blind Sugar Run Reveal" };
                texture.Create(); worldCamera.targetTexture = texture;
                Bounds bounds = StageBounds(fly.Position);
                focus = bounds.center;
                float halfVertical = worldCamera.fieldOfView * Mathf.Deg2Rad * .5f;
                float halfHorizontal = Mathf.Atan(Mathf.Tan(halfVertical) * worldCamera.aspect);
                float distance = Mathf.Max(10, bounds.extents.magnitude / Mathf.Sin(Mathf.Min(halfVertical, halfHorizontal)) * 1.15f);
                destination = focus + new Vector3(.35f, .9f, -1f).normalized * distance;
                worldCamera.farClipPlane = Mathf.Max(previousFarClip, distance + bounds.size.magnitude + 10);
            }
            BuildOverlay();
            conversation?.SetMicrophoneMuted(true);
        }

        Bounds StageBounds(Vector3 fallback)
        {
            Bounds result = new Bounds(fallback, Vector3.one * 4);
            foreach (GameObject root in gameObject.scene.GetRootGameObjects())
            {
                // The authored support geometry alone is used for presentation framing.
                Transform geometry = root.transform.Find("EnvironmentGeometry");
                if (geometry == null) continue;
                foreach (Renderer renderer in geometry.GetComponentsInChildren<Renderer>())
                    if (renderer.enabled && renderer.gameObject.name != "CatchRecovery") result.Encapsulate(renderer.bounds);
            }
            return result;
        }

        void BuildOverlay()
        {
            var template = Resources.Load<PanelSettings>("PlayScreenPanelSettings");
            settings = template != null ? Instantiate(template) : ScriptableObject.CreateInstance<PanelSettings>();
            settings.name = "Blind Sugar Run Reveal Panel"; settings.sortingOrder = 1100;
            settings.scaleMode = PanelScaleMode.ScaleWithScreenSize; settings.referenceResolution = new Vector2Int(1600, 900);
            settings.themeStyleSheet = Resources.Load<ThemeStyleSheet>("PlayScreenTheme");
            // Own a separate document GameObject: the Session also owns the game-over document.
            var canvas = new GameObject("Reveal UI"); canvas.transform.SetParent(transform, false);
            document = canvas.AddComponent<UIDocument>(); document.panelSettings = settings;
            VisualElement root = document.rootVisualElement;
            root.style.flexGrow = 1; root.style.backgroundColor = Color.black;
            root.pickingMode = PickingMode.Position; // Blocks the underlying movement / voice-start controls.
            root.focusable = true; root.Focus();
            font = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic", "Meiryo", "Arial" }, 24);
            root.style.unityFont = font;
            if (texture != null)
            {
                var world = new Image { image = texture, scaleMode = ScaleMode.ScaleToFit, pickingMode = PickingMode.Ignore };
                Fill(world); root.Add(world);
            }
            shade = new VisualElement { pickingMode = PickingMode.Ignore }; Fill(shade);
            shade.style.backgroundColor = Color.black; root.Add(shade);
            title = new Label("SUGAR FOUND"); title.style.position = Position.Absolute;
            title.style.top = 42; title.style.left = 40; title.style.right = 40;
            title.style.fontSize = 36; title.style.color = new Color(1, .87f, .58f);
            title.style.unityTextAlign = TextAnchor.MiddleCenter; root.Add(title);
            var note = new Label(worldCamera != null ? GameLanguage.Text("ここを、歩いてきた。", "This is where we walked.") : GameLanguage.Text("砂糖に到着しました。カメラを利用できません。", "You reached the sugar. The camera is unavailable."));
            note.style.position = Position.Absolute; note.style.bottom = 106; note.style.left = 40; note.style.right = 40;
            note.style.fontSize = 23; note.style.color = Color.white; note.style.unityTextAlign = TextAnchor.MiddleCenter; root.Add(note);
            retry = new Button(() => {
                if (Complete && stage.BeginRetry()) document.rootVisualElement.style.display = DisplayStyle.None;
            }) { text = GameLanguage.Text("もう一度", "Play again") };
            retry.style.position = Position.Absolute; retry.style.bottom = 40; retry.style.width = 200;
            retry.style.height = 48; retry.style.alignSelf = Align.Center; retry.SetEnabled(false); root.Add(retry);
        }

        static void Fill(VisualElement element)
        {
            element.style.position = Position.Absolute; element.style.left = element.style.right = 0;
            element.style.top = element.style.bottom = 0;
        }

        void LateUpdate()
        {
            if (!begun) return;
            float elapsed = Time.unscaledTime - startedAt;
            if (shade != null) shade.style.opacity = 1f - Mathf.Clamp01(elapsed / FadeSeconds);
            if (worldCamera != null)
            {
                float t = Mathf.SmoothStep(0, 1, Mathf.Clamp01((elapsed - FadeSeconds) / PullBackSeconds));
                worldCamera.transform.position = Vector3.Lerp(fromPosition, destination, t);
                Vector3 look = Vector3.Lerp(fromFocus, focus, t);
                worldCamera.transform.rotation = Quaternion.Slerp(fromRotation,
                    Quaternion.LookRotation(look - worldCamera.transform.position, Vector3.up), t);
                if (!RevealStarted)
                {
                    // The image is now attached to the visible overlay; speech never triggers this transition.
                    RevealStarted = true; stage.MarkRevealStarted(); narrator?.NotifyRevealStarted(true);
                    Debug.Log("BLIND_SUGAR_REVEAL_STARTED");
                }
            }
            if (elapsed < EndSeconds || Complete) return;
            StopFinishedGame();
            Complete = true; retry?.SetEnabled(true);
            if (title != null) title.text = "CLEAR — SUGAR FOUND";
            Debug.Log("BLIND_SUGAR_REVEAL_COMPLETE camera=" + (worldCamera != null));
        }

        void StopFinishedGame()
        {
            if (stopped) return;
            stopped = true;
            conversation?.EmergencyStop();
            var body = conversation == null ? null : conversation.GetComponent<NativeConversationBody>();
            if (body != null) body.enabled = false;
            Time.timeScale = 0;
        }

        void OnDestroy()
        {
            if (!begun) return;
            if (!stopped) StopFinishedGame();
            if (worldCamera != null) { worldCamera.targetTexture = previousTexture; worldCamera.farClipPlane = previousFarClip; }
            if (texture != null) { texture.Release(); Destroy(texture); }
            if (document != null) Destroy(document.gameObject);
            if (settings != null) Destroy(settings);
            if (font != null) Destroy(font);
        }
    }
}
