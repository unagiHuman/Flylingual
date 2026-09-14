using Flylingual.Audio;
using Flylingual.Conversation;
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
        Label heading, subtitle, instructions, settingsHeading, connectionStatus;
        Button start, settingsButton, japanese, english, retryConnection;
        ConversationSessionController conversation;
        ConversationNativeBootstrap bootstrap;
        public bool CanStart => conversation != null && conversation.TitleReady;
        public string ConnectionMessage => connectionStatus == null ? string.Empty : connectionStatus.text;
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
            connectionStatus = new Label { name = "title-connection-status" };
            connectionStatus.style.fontSize = 22;
            connectionStatus.style.whiteSpace = WhiteSpace.Normal;
            connectionStatus.style.marginTop = 8;
            cover.Add(connectionStatus);
            start = MakeButton("start-game", StartGame); start.style.width = 360; start.SetEnabled(false); cover.Add(start);
            retryConnection = MakeButton("retry-connection", () => conversation?.RetryTitleConnection());
            retryConnection.style.width = 360; cover.Add(retryConnection);
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
            instructions.style.display = DisplayStyle.Flex;
            instructions.text = !tutorial ? GameLanguage.Text(
                "声でハエを導く、探索ゲーム。\nハエの案内を聞きながら、崖や細い道を越えてゴールを目指します。たどり着くと、歩いてきた世界が見えます。\n\n話しかけよう\n「前へ」「右を向いて」「左を向いて」「止まって」\n\n立ち止まりすぎに注意\n開始後1分間はハエたたきに叩かれません。その後は20秒間ほとんど動かずにいると危険！ 予告が出たら動いて逃げましょう。\n\n失敗しても、もう一度挑戦できます。",
                "An exploration game where your voice guides a fly.\nListen to the fly and navigate cliffs and narrow paths to reach the goal. Finish to reveal the world you travelled through.\n\nTalk to the fly\nSay “forward”, “turn right”, “turn left”, or “stop”.\n\nKeep moving\nYou are safe from the fly swatter for the first minute. After that, staying nearly still for 20 seconds puts you in danger! Move when the warning appears.\n\nIf you fail, you can try again.") : GameLanguage.Text(
                "声でハエに話しかけて、危険を避けてゴールを目指しましょう。\n\n「前へ」「右を向いて」「左を向いて」「止まって」と伝えます。\nハエの案内を聞き、崖やハエたたきなどの危険を避けて進みましょう。ゴールに到着すると、歩いてきた世界が見えます。\n\n困ったときは「緊急停止」。マイクや文字入力はプレイ画面の「設定と診断」から設定できます。\n右上の設定ボタンから、いつでも表示言語を変更できます。",
                "Talk to the fly. Avoid danger and reach the goal.\n\nSay “forward”, “turn right”, “turn left”, or “stop”.\nListen to the fly and avoid hazards such as edges and the fly swatter. Reach the goal to reveal the world you walked through.\n\nUse Emergency stop when needed. Microphone and text input options are in Settings and diagnostics on the play screen.\nChange the display language anytime using Settings at the top right.");
            start.text = tutorial ? GameLanguage.Text("わかった・遊ぶ", "Got it — play") : GameLanguage.Text("はじめる", "Start");
            settingsButton.text = settingsOpen ? GameLanguage.Text("設定を閉じる", "Close settings") : GameLanguage.Text("設定", "Settings");
            settingsHeading.text = GameLanguage.Text("表示言語", "Display language");
            settingsDrawer.style.display = settingsOpen ? DisplayStyle.Flex : DisplayStyle.None;
            japanese.SetEnabled(!GameLanguage.IsJapanese); english.SetEnabled(GameLanguage.IsJapanese);
            RefreshConnection();
        }

        void RefreshConnection()
        {
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            if (bootstrap == null) bootstrap = FindAnyObjectByType<ConversationNativeBootstrap>();
            bool failed = (bootstrap != null && !string.IsNullOrEmpty(bootstrap.StartupError))
                || (conversation != null && !string.IsNullOrEmpty(conversation.Error));
            bool retryable = failed && conversation != null && conversation.Ready;
            connectionStatus.text = CanStart ? GameLanguage.Text("接続完了。ゲームを開始できます。", "Connected. Ready to start.")
                : failed ? (retryable ? GameLanguage.Text("接続できませんでした。接続を確認し、再試行してください。", "Connection failed. Check your connection and retry.")
                    : GameLanguage.Text("接続できませんでした。接続を確認し、アプリを起動し直してください。", "Connection failed. Check your connection and restart the app."))
                : GameLanguage.Text("接続中… 準備が完了するまでお待ちください。", "Connecting… Please wait until everything is ready.");
            start.SetEnabled(CanStart);
            retryConnection.text = GameLanguage.Text("接続を再試行", "Retry connection");
            retryConnection.style.display = retryable && !CanStart ? DisplayStyle.Flex : DisplayStyle.None;
        }

        public void StartGame()
        {
            if (!coverVisible || !CanStart) return;
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

        void Update()
        {
            if (displayedLanguage != GameLanguage.Code) RefreshText();
            else if (coverVisible) RefreshConnection();
        }
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
