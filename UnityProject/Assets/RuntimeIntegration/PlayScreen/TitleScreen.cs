using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.PlayScreen
{
    [DisallowMultipleComponent]
    public sealed class TitleScreen : MonoBehaviour
    {
        public const string ScenePath = "Assets/RuntimeIntegration/PlayScreen/FlylingualTitle.unity";
        public const string InGameScenePath = "Assets/BlindSugarRunPrototype/BlindSugarRunPlay.unity";
        UIDocument document;
        PanelSettings panel;
        Font font;
        Label subtitle, hint, error;
        Button start, japanese, english;

        void Awake()
        {
            var template = Resources.Load<PanelSettings>("PlayScreenPanelSettings");
            panel = template != null ? Instantiate(template) : ScriptableObject.CreateInstance<PanelSettings>();
            panel.referenceResolution = new Vector2Int(1600, 900);
            panel.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            panel.screenMatchMode = PanelScreenMatchMode.MatchWidthOrHeight;
            panel.match = .5f;
            panel.themeStyleSheet = Resources.Load<ThemeStyleSheet>("PlayScreenTheme");
            document = gameObject.AddComponent<UIDocument>();
            document.panelSettings = panel;
            var root = document.rootVisualElement;
            font = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic UI", "Meiryo", "Hiragino Sans", "Arial" }, 24);
            root.style.unityFont = font;
            root.style.flexGrow = 1;
            root.style.backgroundColor = new Color(.025f, .045f, .075f);
            root.style.color = new Color(.96f, .92f, .80f);
            root.style.alignItems = Align.Center;
            root.style.justifyContent = Justify.Center;
            var eyebrow = new Label("BLIND SUGAR RUN");
            eyebrow.style.fontSize = 18; eyebrow.style.letterSpacing = 5;
            eyebrow.style.color = new Color(.38f, .91f, .78f); root.Add(eyebrow);
            var title = new Label("FLYLINGUAL");
            title.style.fontSize = 76; title.style.unityFontStyleAndWeight = FontStyle.Bold;
            title.style.letterSpacing = 7; title.style.marginTop = 16; root.Add(title);
            subtitle = new Label(); subtitle.style.fontSize = 24;
            subtitle.style.marginTop = 12; subtitle.style.marginBottom = 48; root.Add(subtitle);
            start = new Button(StartGame); start.name = "start-game";
            start.style.width = 360; start.style.height = 70; start.style.fontSize = 26;
            start.style.backgroundColor = new Color(1f, .67f, .25f);
            start.style.color = new Color(.025f, .045f, .075f); root.Add(start);
            var languages = new VisualElement(); languages.style.flexDirection = FlexDirection.Row;
            languages.style.marginTop = 28; root.Add(languages);
            japanese = new Button(() => SelectLanguage("ja")) { text = "日本語", name = "language-ja" };
            english = new Button(() => SelectLanguage("en")) { text = "English", name = "language-en" };
            foreach (var button in new[] { japanese, english })
            { button.style.width = 174; button.style.height = 46; button.style.fontSize = 20; languages.Add(button); }
            hint = new Label(); hint.style.fontSize = 16; hint.style.marginTop = 24; root.Add(hint);
            error = new Label(); error.style.fontSize = 18; error.style.marginTop = 18;
            error.style.color = new Color(1f, .5f, .4f); root.Add(error);
            RefreshText();
        }

        void SelectLanguage(string code)
        {
            Flylingual.Audio.SEManager.Instance?.Play(Flylingual.Audio.SEType.UiClick);
            GameLanguage.SetLanguage(code);
            error.text = string.Empty;
            RefreshText();
        }

        void RefreshText()
        {
            subtitle.text = GameLanguage.Text("声を頼りに、砂糖を探そう。", "Follow your voice. Find the sugar.");
            start.text = GameLanguage.Text("はじめる", "Start");
            hint.text = GameLanguage.Text("表示と会話の言語を選択できます", "Choose your display and conversation language");
            japanese.SetEnabled(!GameLanguage.IsJapanese);
            english.SetEnabled(GameLanguage.IsJapanese);
        }

        public void StartGame()
        {
            if (GameSceneTransition.IsLoading) return;
            Flylingual.Audio.SEManager.Instance?.Play(Flylingual.Audio.SEType.StartGame);
            start.SetEnabled(false); japanese.SetEnabled(false); english.SetEnabled(false);
            start.text = GameLanguage.Text("読み込み中…", "Loading…");
            if (!GameSceneTransition.TryLoad(InGameScenePath, message =>
            {
                error.text = message;
                start.SetEnabled(true); RefreshText();
            }))
            { start.SetEnabled(true); RefreshText(); }
        }

        void OnDestroy()
        {
            if (document != null) Destroy(document);
            if (panel != null) Destroy(panel);
            if (font != null) Destroy(font);
        }
    }
}
