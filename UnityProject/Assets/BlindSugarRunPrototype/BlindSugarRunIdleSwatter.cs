using Flylingual.PlayScreen;
using Flylingual.Conversation;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.UIElements;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Game rule only: inactivity is measured from body displacement, never motor intent.</summary>
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunIdleSwatter : MonoBehaviour
    {
        [Min(1f), Tooltip("Total eligible idle seconds, including the warning, before impact.")]
        public float idleSeconds = 20f;
        [Min(0f), Tooltip("Minimum eligible gameplay seconds before the first impact in each attempt.")]
        public float initialGraceSeconds = 60f;
        [Min(.1f)] public float warningSeconds = 4f;
        [Min(.01f), Tooltip("Horizontal displacement from the idle anchor that resets the timer.")]
        public float movementThreshold = .3f;
        public float IdleElapsed { get; private set; }
        public float GameplayElapsed { get; private set; }
        public bool WarningActive { get; private set; }
        public bool Counting { get; private set; }
        public bool Struck { get; private set; }

        BlindSugarRunSession stage;
        ConversationSessionController conversation;
        NativeConversationBody nativeBody;
        Vector3 anchor;
        bool anchored, wasPaused, gameplayStarted;
        GameObject presentation;
        Transform swatter;
        AudioSource audioSource;
        AudioClip warningClip, impactClip;
        Material red, dark;
        Mesh cube;
        Font warningFont;
        UIDocument warningDocument;
        PanelSettings warningPanel;
        Label warningLabel;
        bool presentationInitialized;

        void Awake() { stage = GetComponent<BlindSugarRunSession>(); }

        void Update()
        {
            if (Struck) return;
            // Connections can become ready behind the title. Only the player's
            // Start/first-run confirmation begins either gameplay clock.
            if (TitleScreen.BlocksGameplay)
            { gameplayStarted = false; GameplayElapsed = 0f; ResetIdle(); return; }
            if (stage == null || stage.fly == null || stage.State != BlindSugarRunSession.StageState.Playing)
            { gameplayStarted = false; GameplayElapsed = 0f; ResetIdle(); return; }
            if (conversation == null) conversation = FindFirstObjectByType<ConversationSessionController>();
            if (conversation != null && nativeBody == null) nativeBody = conversation.GetComponent<NativeConversationBody>();
            if (nativeBody != null && nativeBody.BodyActive && conversation != null && conversation.BodyControlActive)
                gameplayStarted = true;
            Vector3 position = stage.fly.Position;
            // A normal STOP still counts. A missing/stale connection or a paused game does not.
            Counting = gameplayStarted && Time.timeScale > 0 && conversation != null && conversation.HasFreshBrain
                && nativeBody != null && string.IsNullOrEmpty(nativeBody.Fault);
            if (!Counting)
            {
                anchor = position; anchored = true; wasPaused = true;
                if (WarningActive) stage.GetComponent<BlindSugarRunNarrator>()?.NotifySwatterEscaped();
                if (WarningActive) stage.GetComponent<BlindSugarRunEnvironmentFeedback>()?.ThreatEnded(false);
                WarningActive = false;
                if (presentation != null) presentation.SetActive(false);
                if (warningLabel != null) warningLabel.style.display = DisplayStyle.None;
                if (audioSource != null) audioSource.Stop();
                return;
            }
            if (!anchored || wasPaused) { anchor = position; anchored = true; wasPaused = false; }
            Vector3 displacement = position - anchor; displacement.y = 0;
            float threshold = Mathf.Max(.01f, movementThreshold);
            if (displacement.sqrMagnitude >= threshold * threshold)
            {
                bool escaped = WarningActive;
                ResetIdle(true); anchor = position; anchored = true; Counting = true;
                if (escaped) Debug.Log("BLIND_SUGAR_SWATTER_ESCAPED position=" + position);
            }
            IdleElapsed += Time.deltaTime;
            GameplayElapsed += Time.deltaTime;
            float total = Mathf.Max(1f, idleSeconds);
            float warning = Mathf.Clamp(warningSeconds, .1f, total);
            // Both conditions must elapse. Movement resets only idle time, while
            // pause/disconnection freezes both clocks and Retry creates a new attempt.
            float remaining = Mathf.Max(total - IdleElapsed, Mathf.Max(0f, initialGraceSeconds) - GameplayElapsed);
            if (remaining > warning) return;
            if (!WarningActive)
            {
                WarningActive = true;
                stage.GetComponent<BlindSugarRunEnvironmentFeedback>()?.ThreatStarted();
                BuildPresentation();
                stage.GetComponent<BlindSugarRunNarrator>()?.NotifySwatterWarning();
                if (audioSource != null) audioSource.PlayOneShot(warningClip, .5f);
                Debug.Log("BLIND_SUGAR_SWATTER_WARNING idleSeconds=" + IdleElapsed + " position=" + position);
            }
            if (warningLabel != null)
            {
                warningLabel.style.display = DisplayStyle.Flex;
                warningLabel.text = GameLanguage.Text("ハエたたきが来る！ 動いて逃げよう\nあと ", "A fly swatter is coming! Move to escape!\nTime left: ")
                    + Mathf.CeilToInt(Mathf.Max(0, remaining)) + GameLanguage.Text(" 秒", " seconds");
            }
            if (presentation != null && swatter != null)
            {
                presentation.SetActive(true);
                // The final fast descent is part of the warning: escape remains possible until impact.
                float height = remaining > .25f ? Mathf.Lerp(5f, 2.8f, Mathf.Clamp01((warning - remaining) / warning))
                    : Mathf.Lerp(.1f, 2.8f, Mathf.Clamp01(remaining / .25f));
                swatter.position = new Vector3(anchor.x, position.y + height, anchor.z);
                swatter.rotation = Quaternion.Euler(0, 20, remaining > .25f ? Mathf.Sin(IdleElapsed * 9) * 6 : 0);
            }
            if (remaining > 0f) return;
            Struck = true; Counting = false; WarningActive = false;
            if (warningLabel != null) warningLabel.style.display = DisplayStyle.None;
            if (audioSource != null) audioSource.PlayOneShot(impactClip, .85f);
            stage.KillBySwatter();
        }

        void ResetIdle(bool escaped = false)
        {
            if (WarningActive && stage != null) stage.GetComponent<BlindSugarRunEnvironmentFeedback>()?.ThreatEnded(escaped);
            if (WarningActive && stage != null) stage.GetComponent<BlindSugarRunNarrator>()?.NotifySwatterEscaped();
            IdleElapsed = 0; WarningActive = false; Counting = false; anchored = false; wasPaused = false;
            if (presentation != null) presentation.SetActive(false);
            if (warningLabel != null) warningLabel.style.display = DisplayStyle.None;
            if (audioSource != null) audioSource.Stop();
        }

        void BuildPresentation()
        {
            if (presentationInitialized) return;
            presentationInitialized = true;
            // Cosmetic initialization must not prevent the idle rule reaching KillBySwatter.
            BuildPresentationPart("warning UI", BuildWarningUI);
            BuildPresentationPart("audio", BuildAudio);
            BuildPresentationPart("geometry", BuildGeometry);
        }

        void BuildPresentationPart(string part, System.Action build)
        {
            try { build(); }
            catch (System.Exception exception)
            {
                Debug.LogWarning("BLIND_SUGAR_SWATTER_PRESENTATION_UNAVAILABLE part=" + part + " " + exception.Message, this);
            }
        }

        void BuildGeometry()
        {
            // Resources includes this shader in Players; Shader.Find-only shaders can be stripped.
            Shader shader = Resources.Load<Shader>("IdleSwatter");
            if (shader == null || !shader.isSupported)
                throw new System.InvalidOperationException("IdleSwatter shader is missing or unsupported.");
            red = new Material(shader) { color = new Color(.8f, .12f, .08f) };
            dark = new Material(shader) { color = new Color(.16f, .1f, .08f) };
            presentation = new GameObject("Idle swatter presentation (no physics)");
            presentation.transform.SetParent(transform, false);
            swatter = presentation.transform;
            // A shared authored cube mesh avoids even transient primitive colliders.
            cube = new Mesh { name = "Swatter presentation cube" };
            cube.vertices = new[] { new Vector3(-.5f,-.5f,-.5f), new Vector3(.5f,-.5f,-.5f), new Vector3(.5f,.5f,-.5f), new Vector3(-.5f,.5f,-.5f),
                new Vector3(-.5f,-.5f,.5f), new Vector3(.5f,-.5f,.5f), new Vector3(.5f,.5f,.5f), new Vector3(-.5f,.5f,.5f) };
            cube.triangles = new[] { 0,2,1,0,3,2, 4,5,6,4,6,7, 0,1,5,0,5,4, 3,7,6,3,6,2, 0,4,7,0,7,3, 1,2,6,1,6,5 };
            cube.RecalculateNormals(); cube.RecalculateBounds();
            Bar("Handle", new Vector3(0, 0, -2.6f), new Vector3(.18f, .12f, 3.2f), dark);
            for (int i = 0; i < 7; i++)
            {
                float offset = -1.2f + i * .4f;
                Bar("Mesh X", new Vector3(0, 0, offset), new Vector3(2.5f, .1f, .08f), red);
                Bar("Mesh Z", new Vector3(offset, 0, 0), new Vector3(.08f, .1f, 2.5f), red);
            }
        }

        void BuildAudio()
        {
            // Audio lives on the session so hiding the geometry cannot truncate impact playback.
            audioSource = gameObject.AddComponent<AudioSource>();
            audioSource.playOnAwake = false; audioSource.spatialBlend = 0; audioSource.ignoreListenerPause = true;
            warningClip = MakeCue(false); impactClip = MakeCue(true);
        }

        void BuildWarningUI()
        {
            var template = Resources.Load<PanelSettings>("PlayScreenPanelSettings");
            warningPanel = template != null ? Instantiate(template) : ScriptableObject.CreateInstance<PanelSettings>();
            warningPanel.sortingOrder = 900;
            warningPanel.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            warningPanel.referenceResolution = new Vector2Int(1600, 900);
            warningPanel.themeStyleSheet = Resources.Load<ThemeStyleSheet>("PlayScreenTheme");
            // A child UIDocument inherits the session's hidden GameOver document.
            // Keep this presentation in the same scene with an independent panel.
            var overlay = new GameObject("Swatter warning UI");
            UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(overlay, gameObject.scene);
            warningDocument = overlay.AddComponent<UIDocument>(); warningDocument.panelSettings = warningPanel;
            var root = warningDocument.rootVisualElement;
            root.pickingMode = PickingMode.Ignore;
            root.style.position = Position.Absolute;
            root.style.left = root.style.right = root.style.top = root.style.bottom = 0;
            warningFont = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic", "Meiryo", "Arial" }, 24);
            warningLabel = new Label { pickingMode = PickingMode.Ignore };
            warningLabel.style.position = Position.Absolute;
            warningLabel.style.top = 85; warningLabel.style.left = Length.Percent(25); warningLabel.style.right = Length.Percent(25);
            warningLabel.style.paddingTop = warningLabel.style.paddingBottom = 12;
            warningLabel.style.unityFont = warningFont; warningLabel.style.fontSize = 24;
            warningLabel.style.unityTextAlign = TextAnchor.MiddleCenter;
            warningLabel.style.whiteSpace = WhiteSpace.Normal;
            warningLabel.style.color = new Color(1f, .85f, .35f);
            warningLabel.style.backgroundColor = new Color(.15f, .025f, .02f, .95f);
            root.Add(warningLabel);
        }

        void Bar(string label, Vector3 position, Vector3 size, Material material)
        {
            var part = new GameObject(label); part.transform.SetParent(swatter, false);
            part.transform.localPosition = position; part.transform.localScale = size;
            part.AddComponent<MeshFilter>().sharedMesh = cube;
            var renderer = part.AddComponent<MeshRenderer>(); renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off; renderer.receiveShadows = false;
        }

        static AudioClip MakeCue(bool impact)
        {
            const int rate = 22050;
            float duration = impact ? .23f : .7f;
            var samples = new float[Mathf.CeilToInt(rate * duration)];
            for (int i = 0; i < samples.Length; i++)
            {
                float t = (float)i / rate;
                float envelope = Mathf.Min(1f, t / .008f) * Mathf.Exp(-t * (impact ? 22f : 4f));
                float tone = impact ? Mathf.Sin(2 * Mathf.PI * 120 * t) + .45f * Mathf.Sin(2 * Mathf.PI * 1741 * t)
                    : Mathf.Sin(2 * Mathf.PI * (700 * t + 600 * t * t));
                samples[i] = tone * envelope * .45f;
            }
            var clip = AudioClip.Create(impact ? "Swatter impact" : "Swatter warning", samples.Length, 1, rate, false);
            clip.SetData(samples, 0); return clip;
        }

        void OnDisable() { if (!Struck) ResetIdle(); }
        void OnDestroy()
        {
            if (presentation != null) Destroy(presentation);
            if (audioSource != null) Destroy(audioSource);
            if (warningClip != null) Destroy(warningClip);
            if (impactClip != null) Destroy(impactClip);
            if (red != null) Destroy(red);
            if (dark != null) Destroy(dark);
            if (cube != null) Destroy(cube);
            if (warningFont != null) Destroy(warningFont);
            if (warningDocument != null) Destroy(warningDocument.gameObject);
            if (warningPanel != null) Destroy(warningPanel);
        }
    }
}
