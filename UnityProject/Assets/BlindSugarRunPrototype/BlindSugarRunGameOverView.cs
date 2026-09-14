using Flylingual.PlayScreen;
using System;
using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Independent game-over and retry overlay for the Blind Sugar Run prototype.</summary>
    public sealed class BlindSugarRunGameOverView : MonoBehaviour
    {
        UIDocument document;
        PanelSettings panelSettings;
        Font ownedFont;
        VisualElement root;
        Label titleLabel, messageLabel, attemptLabel;
        Action retryHandler;
        bool retryConsumed, busy;
        string displayedLanguage, shownTitle, shownMessage;
        int shownAttempt;

        public bool Visible => root != null && root.style.display == DisplayStyle.Flex;
        public Button RetryButton { get; private set; }

        void Awake()
        {
            Build();
            Hide();
        }

        void Build()
        {
            if (document != null) return;
            PanelSettings template = Resources.Load<PanelSettings>("PlayScreenPanelSettings");
            panelSettings = template != null ? Instantiate(template) : ScriptableObject.CreateInstance<PanelSettings>();
            panelSettings.name = "Blind Sugar Run Game Over Panel Settings";
            panelSettings.referenceResolution = new Vector2Int(1600, 900);
            panelSettings.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            panelSettings.screenMatchMode = PanelScreenMatchMode.MatchWidthOrHeight;
            panelSettings.match = .5f;
            panelSettings.sortingOrder = 1000;
            panelSettings.themeStyleSheet = Resources.Load<ThemeStyleSheet>("PlayScreenTheme");
            document = gameObject.AddComponent<UIDocument>();
            document.panelSettings = panelSettings;
            document.rootVisualElement.pickingMode = PickingMode.Ignore;
            root = new VisualElement { name = "blind-sugar-run-game-over" };
            root.style.position = Position.Absolute;
            root.style.left = 0; root.style.right = 0; root.style.top = 0; root.style.bottom = 0;
            root.style.alignItems = Align.Center; root.style.justifyContent = Justify.Center;
            root.style.backgroundColor = new Color(.015f, .025f, .075f, .86f);
            root.pickingMode = PickingMode.Position;
            document.rootVisualElement.Add(root);

            VisualElement card = new VisualElement { name = "game-over-card" };
            card.style.width = 440; card.style.maxWidth = Length.Percent(90); card.style.paddingLeft = 30; card.style.paddingRight = 30;
            card.style.paddingTop = 26; card.style.paddingBottom = 24; card.style.backgroundColor = new Color(.055f, .086f, .15f, .99f);
            card.style.borderTopLeftRadius = card.style.borderTopRightRadius = card.style.borderBottomLeftRadius = card.style.borderBottomRightRadius = 12;
            root.Add(card);
            ownedFont = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic UI", "Meiryo", "MS Gothic" }, 18);
            card.style.unityFont = ownedFont;
            titleLabel = Text(card, GameLanguage.Text("状況", "Status"), 28, FontStyle.Bold);
            messageLabel = Text(card, string.Empty, 16, FontStyle.Normal); messageLabel.style.whiteSpace = WhiteSpace.Normal; messageLabel.style.marginTop = 14;
            attemptLabel = Text(card, string.Empty, 13, FontStyle.Normal); attemptLabel.style.marginTop = 12; attemptLabel.style.opacity = .72f;
            RetryButton = new Button(OnRetryClicked) { text = GameLanguage.Text("もう一度挑戦する", "Try again"), name = "retry-button" };
            RetryButton.style.marginTop = 22; RetryButton.style.height = 44; RetryButton.style.fontSize = 16; RetryButton.style.unityFontStyleAndWeight = FontStyle.Bold;
            RetryButton.style.backgroundColor = new Color(.18f, .62f, .50f, 1f); RetryButton.style.color = Color.white;
            card.Add(RetryButton);
        }

        public void Show(string title, string message, int attempt, Action retry)
        {
            Build();
            retryHandler = retry;
            retryConsumed = false;
            busy = false; shownTitle = title; shownMessage = message; shownAttempt = attempt;
            RefreshLanguage();
            RetryButton.SetEnabled(true);
            root.style.display = DisplayStyle.Flex;
            document.rootVisualElement.style.display = DisplayStyle.Flex;
            RetryButton.Focus();
        }

        public void ShowBusy(string message, int attempt)
        {
            Build();
            retryConsumed = true;
            busy = true; shownTitle = null; shownMessage = message; shownAttempt = attempt;
            RefreshLanguage();
            RetryButton.SetEnabled(false);
            root.style.display = DisplayStyle.Flex;
            document.rootVisualElement.style.display = DisplayStyle.Flex;
        }

        void Update()
        {
            if (Visible && displayedLanguage != GameLanguage.Code) RefreshLanguage();
        }

        void RefreshLanguage()
        {
            displayedLanguage = GameLanguage.Code;
            titleLabel.text = busy ? GameLanguage.Text("リトライ中", "Retrying")
                : string.IsNullOrEmpty(shownTitle) ? GameLanguage.Text("ゲームオーバー", "Game over") : LocalizeKnownText(shownTitle);
            messageLabel.text = shownMessage == null
                ? (busy ? GameLanguage.Text("再開しています…", "Resuming…") : string.Empty) : LocalizeKnownText(shownMessage);
            attemptLabel.text = GameLanguage.Text("挑戦 ", "Attempt ") + Mathf.Max(1, shownAttempt);
            RetryButton.text = busy ? GameLanguage.Text("再開中…", "Resuming…") : GameLanguage.Text("もう一度挑戦する", "Try again");
        }

        // Show accepts caller-owned text. Re-render only known fixed messages; preserve diagnostics verbatim.
        static readonly string[,] FixedMessages = {
            { "ゲームオーバー", "GAME OVER" },
            { "プレイを中断しました", "Play interrupted" },
            { "再開の準備ができませんでした", "Unable to resume" },
            { "開始地点と音声操作を準備しています…", "Preparing the starting point and voice controls…" },
            { "開始地点へ戻っています…", "Returning to the starting point…" },
            { "崖から落下しました。\n開始地点からもう一度挑戦できます。", "You fell off the edge.\nTry again from the starting point." },
            { "落下時の接続状態を確認できませんでした。\n接続を確認して、開始地点からやり直してください。", "The connection could not be verified when you fell.\nCheck the connection and try again." },
            { "動かずにいたため、ハエたたきに叩かれました。\n開始地点からもう一度挑戦できます。", "You stayed still and were hit by the fly swatter.\nTry again from the starting point." }
        };
        static string LocalizeKnownText(string value)
        {
            for (int i = 0; i < FixedMessages.GetLength(0); i++)
                if (value == FixedMessages[i, 0] || value == FixedMessages[i, 1])
                    return GameLanguage.Text(FixedMessages[i, 0], FixedMessages[i, 1]);
            return value;
        }
        public void Hide()
        {
            if (root != null) root.style.display = DisplayStyle.None;
            if (document != null) document.rootVisualElement.style.display = DisplayStyle.None;
            retryHandler = null;
            retryConsumed = false;
        }

        void OnRetryClicked()
        {
            if (retryConsumed) return;
            retryConsumed = true;
            RetryButton.SetEnabled(false);
            retryHandler?.Invoke();
        }

        static Label Text(VisualElement parent, string value, int size, FontStyle style)
        {
            var label = new Label(value);
            label.style.fontSize = size; label.style.unityFontStyleAndWeight = style; label.style.color = new Color(.96f, .94f, .86f);
            parent.Add(label); return label;
        }

        void OnDestroy()
        {
            retryHandler = null;
            if (ownedFont != null) Destroy(ownedFont);
            if (panelSettings != null) Destroy(panelSettings);
            if (document != null) Destroy(document);
        }
    }
}
