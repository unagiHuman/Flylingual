using Flylingual.Audio;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

namespace Flylingual.PlayScreen
{
    /// <summary>Title, first-run instructions and always available settings in the gameplay scene.</summary>
    [DefaultExecutionOrder(-2000)]
    [DisallowMultipleComponent]
    public sealed class TitleScreen : MonoBehaviour
    {
        public const string ScenePath = "Assets/RuntimeIntegration/PlayScreen/FlylingualTitle.unity";
        public const string InGameScenePath = "Assets/BlindSugarRunPrototype/BlindSugarRunPlay.unity";
        const string TutorialKey = "Flylingual.Prototype.InstructionsCompleted.v1";
        static TitleScreen instance;
        static bool presented;
        public static bool BlocksGameplay => instance != null && instance.coverVisible;
        UIDocument document;
        PanelSettings panel;
        Font font;
        VisualElement cover, settingsDrawer;
        Label heading, subtitle, instructions, settingsHeading;
        Button start, settingsButton, japanese, english;
        bool coverVisible = true, tutorial, settingsOpen;
        string displayedLanguage;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetState() { instance = null; presented = false; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (SceneManager.GetActiveScene().path == InGameScenePath && instance == null)
                new GameObject("Flylingual Front End").AddComponent<TitleScreen>();
        }

        void Awake()
        {
            if (instance != null && instance != this) { Destroy(gameObject); return; }
            instance = this;
            coverVisible = !presented;
            presented = true;
            DontDestroyOnLoad(gameObject);
            var template = Resources.Load<PanelSettings>("PlayScreenPanelSettings");
            panel = template != null ? Instantiate(template) : ScriptableObject.CreateInstance<PanelSettings>();
            panel.sortingOrder = 3000;
            panel.referenceResolution = new Vector2Int(1600, 900);
            panel.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            panel.screenMatchMode = PanelScreenMatchMode.MatchWidthOrHeight;
            panel.match = .5f;
            panel.themeStyleSheet = Resources.Load<ThemeStyleSheet>("PlayScreenTheme");
            document = gameObject.AddComponent<UIDocument>();
            document.panelSettings = panel;
            var root = document.rootVisualElement;
            root.pickingMode = PickingMode.Ignore;
            root.style.flexGrow = 1;
            root.style.color = new Color(.96f, .92f, .80f);
            font = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic UI", "Meiryo", "Hiragino Sans", "Arial" }, 24);
            root.style.unityFont = font;
            cover = new VisualElement { name = "title-overlay" };
            cover.style.position = Position.Absolute;
            cover.style.left = cover.style.right = cover.style.top = cover.style.bottom = 0;
            cover.style.backgroundColor = new Color(.025f, .045f, .075f);
            cover.style.alignItems = Align.Center;
            cover.style.justifyContent = Justify.Center;
            cover.style.paddingLeft = cover.style.paddingRight = 36;
            root.Add(cover);
            heading = new Label(); heading.style.fontSize = 64;
            heading.style.unityFontStyleAndWeight = FontStyle.Bold; cover.Add(heading);
            subtitle = new Label(); subtitle.style.fontSize = 23;
            subtitle.style.marginTop = 16; subtitle.style.marginBottom = 28; cover.Add(subtitle);
            instructions = new Label { name = "first-run-instructions" };
            instructions.style.whiteSpace = WhiteSpace.Normal;
            instructions.style.maxWidth = 900; instructions.style.fontSize = 24;
            instructions.style.marginBottom = 28; cover.Add(instructions);
            start = MakeButton("start-game", StartGame); start.style.width = 360; cover.Add(start);
            settingsDrawer = new VisualElement { name = "global-settings" };
            settingsDrawer.style.position = Position.Absolute;
            settingsDrawer.style.top = 86; settingsDrawer.style.right = 24;
            settingsDrawer.style.width = 330;
            settingsDrawer.style.paddingLeft = settingsDrawer.style.paddingRight = 20;
            settingsDrawer.style.paddingTop = settingsDrawer.style.paddingBottom = 20;
            settingsDrawer.style.backgroundColor = new Color(.055f, .086f, .125f);
            root.Add(settingsDrawer);
            settingsHeading = new Label(); settingsHeading.style.fontSize = 22; settingsDrawer.Add(settingsHeading);
            japanese = MakeButton("language-ja", () => SelectLanguage("ja")); japanese.text = "日本語"; settingsDrawer.Add(japanese);
            english = MakeButton("language-en", () => SelectLanguage("en")); english.text = "English"; settingsDrawer.Add(english);
            settingsButton = MakeButton("global-settings-button", () => { settingsOpen = !settingsOpen; RefreshText(); });
            settingsButton.style.position = Position.Absolute; settingsButton.style.top = 20; settingsButton.style.right = 24;
            settingsButton.style.width = 220; root.Add(settingsButton);
            RefreshText();
            if (coverVisible) Time.timeScale = 0f;
        }

        static Button MakeButton(string name, System.Action clicked)
        {
            var button = new Button(() => { SEManager.Instance?.Play(SEType.UiClick); clicked(); }) { name = name };
            button.style.height = 54; button.style.fontSize = 22; button.style.marginTop = 10;
            button.style.backgroundColor = new Color(1f, .67f, .25f);
            button.style.color = new Color(.025f, .045f, .075f);
            return button;
        }

        void SelectLanguage(string code)
        {
            GameLanguage.SetLanguage(code);
            RefreshText();
        }

        void RefreshText()
        {
            displayedLanguage = GameLanguage.Code;
            cover.style.display = coverVisible ? DisplayStyle.Flex : DisplayStyle.None;
            heading.text = tutorial ? GameLanguage.Text("遊び方", "How to play") : "FLYLINGUAL";
            subtitle.text = tutorial ? GameLanguage.Text("説明中はゲームの時間が止まっています。", "The game is paused while you read.")
                : GameLanguage.Text("声を頼りに、危険を避けてゴールを目指そう。", "Avoid danger and reach the goal.");
            instructions.style.display = tutorial ? DisplayStyle.Flex : DisplayStyle.None;
            instructions.text = GameLanguage.Text(
                "声でハエに話しかけて、危険を避けてゴールを目指しましょう。\n\n「前へ」「右を向いて」「左を向いて」「止まって」と伝えます。\nハエの案内を聞き、崖やハエたたきなどの危険を避けて進みましょう。ゴールに到着すると、歩いてきた世界が見えます。\n\n困ったときは「緊急停止」。マイクや文字入力はプレイ画面の「設定と診断」から設定できます。\n右上の設定ボタンから、いつでも表示言語を変更できます。",
                "Talk to the fly. Avoid danger and reach the goal.\n\nSay “forward”, “turn right”, “turn left”, or “stop”.\nListen to the fly and avoid hazards such as edges and the fly swatter. Reach the goal to reveal the world you walked through.\n\nUse Emergency stop when needed. Microphone and text input options are in Settings and diagnostics on the play screen.\nChange the display language anytime using Settings at the top right.");
            start.text = tutorial ? GameLanguage.Text("わかった・遊ぶ", "Got it — play") : GameLanguage.Text("はじめる", "Start");
            settingsButton.text = settingsOpen ? GameLanguage.Text("設定を閉じる", "Close settings") : GameLanguage.Text("設定", "Settings");
            settingsHeading.text = GameLanguage.Text("表示言語", "Display language");
            settingsDrawer.style.display = settingsOpen ? DisplayStyle.Flex : DisplayStyle.None;
            japanese.SetEnabled(!GameLanguage.IsJapanese); english.SetEnabled(GameLanguage.IsJapanese);
        }

        public void StartGame()
        {
            if (!coverVisible) return;
            if (!tutorial && PlayerPrefs.GetInt(TutorialKey, 0) == 0)
            {
                tutorial = true; RefreshText(); return;
            }
            if (tutorial) { PlayerPrefs.SetInt(TutorialKey, 1); PlayerPrefs.Save(); }
            coverVisible = false;
            SEManager.Instance?.Play(SEType.StartGame);
            RefreshText();
            // Native body control resumes only after its existing live Brain safety gate.
            if (!Flylingual.Conversation.NativeConversationRuntime.Enabled) Time.timeScale = 1f;
        }

        void Update() { if (displayedLanguage != GameLanguage.Code) RefreshText(); }
        void LateUpdate() { if (coverVisible) Time.timeScale = 0f; }
        void OnDestroy()
        {
            if (instance == this) instance = null;
            if (document != null) Destroy(document);
            if (panel != null) Destroy(panel);
            if (font != null) Destroy(font);
        }
    }
}
