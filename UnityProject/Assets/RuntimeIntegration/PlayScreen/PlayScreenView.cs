using System;
using System.Collections.Generic;
using FlyBrainVisualization;
using Flylingual.Conversation;
using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.PlayScreen
{
    /// <summary>Runtime UIToolkit play surface. It observes existing systems and owns only its document resources.</summary>
    [DisallowMultipleComponent]
    public sealed class PlayScreenView : MonoBehaviour
    {
        readonly Color navy = new Color(.025f, .045f, .075f);
        readonly Color panel = new Color(.055f, .086f, .125f, .96f);
        readonly Color cream = new Color(.96f, .92f, .80f);
        readonly Color amber = new Color(1f, .67f, .25f);
        readonly Color mint = new Color(.38f, .91f, .78f);

        UIDocument document;
        PanelSettings panelSettings;
        Font uiFont;
        Texture gameTexture;
        NeuralVisualizationPanel neural;
        ConversationSessionController controller;
        ConversationNativeBootstrap bootstrap;
        Image gameImage, neuralImage;
        Label blindMessage;
        Label statusLabel, controlModeLabel, actionFeedbackLabel, captionLabel, portraitSource, portraitObservation, neuralStatus, diagnostics, transcriptLabel;
        FlyPortraitElement portrait;
        TextField textInput, personaText;
        Slider volume, gain;
        DropdownField deviceField, languageField, voiceField, personaField;
        Button startButton, stopButton, muteButton, voiceButton, applyButton, sendButton, settingsButton;
        VisualElement gameFrame, settingsDrawer;
        bool pointerOverControls, built, settingsOpen;
        float nextRefresh;
        int displayedSettingsRevision = -1;
        string language = "ja", voice = "marin", persona = "friendly";

        public bool IsBuilt => built;
        public bool SettingsOpen => settingsOpen;
        public Rect GameImageScreenRect { get; private set; }
        public bool BlocksGameInput => pointerOverControls || TextInputHasFocus;
        public string DiagnosticsSummary { get; private set; }

        bool TextInputHasFocus
        {
            get
            {
                Focusable focused = textInput == null || textInput.focusController == null ? null : textInput.focusController.focusedElement;
                return focused is VisualElement element && textInput.Contains(element);
            }
        }

        void Awake() => Build();

        public void Configure(Texture texture, NeuralVisualizationPanel neuralPanel)
        {
            gameTexture = texture;
            neural = neuralPanel;
            Build();
            SetGameTexture(texture);
            BootstrapExistingController();
        }

        public void SetGameTexture(Texture texture)
        {
            gameTexture = texture;
            if (gameImage != null) gameImage.image = texture;
            UpdateGameImageRect();
        }

        public void SetBlindMode(bool blind)
        {
            if (gameImage == null || blindMessage == null) return;
            gameImage.style.display = blind ? DisplayStyle.None : DisplayStyle.Flex;
            blindMessage.style.display = blind ? DisplayStyle.Flex : DisplayStyle.None;
        }

        void Build()
        {
            if (built) return;
            var panelTemplate = Resources.Load<PanelSettings>("PlayScreenPanelSettings");
            panelSettings = panelTemplate != null ? Instantiate(panelTemplate) : ScriptableObject.CreateInstance<PanelSettings>();
            panelSettings.name = "Flylingual Play Screen Panel Settings";
            panelSettings.referenceResolution = new Vector2Int(1600, 900);
            panelSettings.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            panelSettings.screenMatchMode = PanelScreenMatchMode.MatchWidthOrHeight;
            panelSettings.match = .5f;
            panelSettings.themeStyleSheet = Resources.Load<ThemeStyleSheet>("PlayScreenTheme");
            document = gameObject.AddComponent<UIDocument>();
            document.panelSettings = panelSettings;
            VisualElement root = document.rootVisualElement;
            root.style.flexGrow = 1; root.style.backgroundColor = navy; root.style.color = cream;
            root.style.fontSize = 16; uiFont = JapaneseFont(); root.style.unityFont = uiFont;
            root.style.paddingLeft = root.style.paddingRight = 16; root.style.paddingTop = root.style.paddingBottom = 14;

            var header = Row("header"); header.style.height = 58; header.style.alignItems = Align.Center;
            var title = Label("FLYLINGUAL", 27, amber, FontStyle.Bold); title.style.letterSpacing = 2; header.Add(title);
            var subtitle = Label("ハエと話し、行動と神経活動を観察する", 14, cream); subtitle.style.marginLeft = 16; subtitle.style.opacity = .82f; header.Add(subtitle);
            header.Add(Spacer()); statusLabel = Label("接続を確認中", 13, mint); statusLabel.style.unityTextAlign = TextAnchor.MiddleRight; header.Add(statusLabel); root.Add(header);

            var main = Row("main"); main.style.flexGrow = 1; main.style.minHeight = 260; main.style.marginBottom = 12; root.Add(main);
            gameFrame = Card(); gameFrame.style.flexGrow = 7; gameFrame.style.flexBasis = 0; gameFrame.style.marginRight = 12; main.Add(gameFrame);
            var gameTitle = Label("ゲーム画面 / GAME VIEW", 13, amber, FontStyle.Bold); gameTitle.style.marginLeft = 14; gameTitle.style.marginTop = 12; gameFrame.Add(gameTitle);
            gameImage = new Image { scaleMode = ScaleMode.ScaleToFit }; gameImage.style.flexGrow = 1; gameImage.style.marginLeft = gameImage.style.marginRight = 10; gameImage.style.marginBottom = 10; gameFrame.Add(gameImage);
            blindMessage = Label("BLIND SUGAR RUN\n\n声を頼りに、砂糖を探そう。\nたどり着いたら、歩いてきた世界が見える。", 22, cream);
            blindMessage.style.flexGrow = 1; blindMessage.style.unityTextAlign = TextAnchor.MiddleCenter;
            blindMessage.style.whiteSpace = WhiteSpace.Normal; blindMessage.style.display = DisplayStyle.None; gameFrame.Add(blindMessage);
            gameFrame.RegisterCallback<GeometryChangedEvent>(_ => UpdateGameImageRect());

            var side = new VisualElement(); side.style.flexGrow = 3; side.style.flexBasis = 0; side.style.minWidth = 260; side.style.flexDirection = FlexDirection.Column; main.Add(side);
            var neuralCard = Card(); neuralCard.style.flexGrow = 1; neuralCard.style.flexBasis = 0; neuralCard.style.marginBottom = 12; side.Add(neuralCard);
            var neuralTitle = Label("脳・神経活動 · 橙色は実測発火", 13, mint, FontStyle.Bold);
            neuralTitle.tooltip = "受信した計測窓で発火した細胞が光ります。短い残光を含みます。灰色は細胞の位置で、発火ではありません。";
            neuralCard.Add(neuralTitle);
            neuralImage = new Image { scaleMode = ScaleMode.ScaleToFit }; neuralImage.style.flexGrow = 1; neuralImage.style.minHeight = 90; neuralImage.style.marginTop = 7; neuralCard.Add(neuralImage);
            neuralStatus = Label("可視化データを待機中", 12, cream); neuralStatus.style.opacity = .8f; neuralStatus.style.whiteSpace = WhiteSpace.Normal; neuralCard.Add(neuralStatus);
            RegisterControlSurface(neuralCard);
            neuralImage.RegisterCallback<PointerMoveEvent>(evt => { if (evt.pressedButtons != 0 && neural != null) neural.Rotate(evt.deltaPosition); });
            neuralImage.RegisterCallback<WheelEvent>(evt => { if (neural != null) { neural.Zoom(evt.delta.y); evt.StopPropagation(); } });

            var portraitCard = Card(); portraitCard.style.flexGrow = 1; portraitCard.style.flexBasis = 0; side.Add(portraitCard);
            portraitCard.Add(Label("ハエリンガル / FLYLINGUAL", 13, amber, FontStyle.Bold));
            portrait = new FlyPortraitElement(); portrait.style.flexGrow = 1; portrait.style.minHeight = 96; portraitCard.Add(portrait);
            portraitSource = Label("表現の根拠: 接続状態", 12, mint); portraitCard.Add(portraitSource);
            portraitObservation = Label("気持ちはまだわかりません", 12, cream); portraitObservation.style.whiteSpace = WhiteSpace.Normal; portraitCard.Add(portraitObservation);

            var controls = Card(); controls.style.flexShrink = 0; controls.style.paddingTop = 9; controls.style.paddingBottom = 9; root.Add(controls); RegisterControlSurface(controls);
            var actions = Row("actions"); actions.style.alignItems = Align.Center; actions.style.flexWrap = Wrap.Wrap; controls.Add(actions);
            startButton = MakeButton("会話のみ開始", () => controller?.StartConversation()); actions.Add(startButton);
            stopButton = MakeButton("会話を終了", () => controller?.StopConversation()); actions.Add(stopButton);
            var emergency = MakeButton("緊急停止", () => controller?.EmergencyStop()); emergency.style.backgroundColor = new Color(.64f, .18f, .13f); emergency.style.color = Color.white; emergency.style.unityFontStyleAndWeight = FontStyle.Bold; actions.Add(emergency);
            muteButton = MakeButton("マイクをミュート", () => { if (controller != null) controller.SetMicrophoneMuted(!controller.MicrophoneMuted); }); actions.Add(muteButton);
            voiceButton = MakeButton("声で操作を有効にする", () => controller?.EnableVoiceActions()); actions.Add(voiceButton);
            actions.Add(Spacer()); settingsButton = MakeButton("設定と診断", ToggleSettingsDrawer); actions.Add(settingsButton);
            controlModeLabel = Label("操作状況: 停止中", 13, mint, FontStyle.Bold); controlModeLabel.style.marginTop = 5; controls.Add(controlModeLabel);
            actionFeedbackLabel = Label(string.Empty, 13, cream); actionFeedbackLabel.style.whiteSpace = WhiteSpace.Normal; controls.Add(actionFeedbackLabel);
            captionLabel = Label("字幕: 接続待ち", 14, cream); captionLabel.style.marginTop = 7; captionLabel.style.whiteSpace = WhiteSpace.Normal; captionLabel.style.maxHeight = 42; captionLabel.style.overflow = Overflow.Hidden; controls.Add(captionLabel);
            diagnostics = Label(string.Empty, 11, cream); diagnostics.style.opacity = .66f; diagnostics.style.display = DisplayStyle.None; controls.Add(diagnostics);
            settingsDrawer = Card(); settingsDrawer.style.position = Position.Absolute; settingsDrawer.style.right = 16; settingsDrawer.style.bottom = 96; settingsDrawer.style.width = 430; settingsDrawer.style.maxHeight = 360; settingsDrawer.style.display = DisplayStyle.None; root.Add(settingsDrawer); RegisterControlSurface(settingsDrawer);
            settingsDrawer.style.backgroundColor = new Color(.055f, .086f, .125f, 1f);
            settingsDrawer.style.borderTopWidth = settingsDrawer.style.borderBottomWidth = settingsDrawer.style.borderLeftWidth = settingsDrawer.style.borderRightWidth = 1;
            settingsDrawer.style.borderTopColor = settingsDrawer.style.borderBottomColor = settingsDrawer.style.borderLeftColor = settingsDrawer.style.borderRightColor = mint;
            BuildSettings(settingsDrawer);
            built = true;
            BootstrapExistingController();
            SetActionAvailability(false);
            SetGameTexture(gameTexture);
        }

        void BuildSettings(VisualElement settings)
        {
            var scroll = new ScrollView(ScrollViewMode.Vertical); scroll.style.maxHeight = 300; settings.Add(scroll);
            scroll.Add(Label("マイク入力と出力", 12, mint, FontStyle.Bold));
            deviceField = new DropdownField("マイク"); deviceField.RegisterValueChangedCallback(e => controller?.SetMicrophoneDevice(e.newValue)); scroll.Add(deviceField);
            volume = new Slider("音量", 0, 1); volume.RegisterValueChangedCallback(e => controller?.SetVolume(e.newValue)); scroll.Add(volume);
            languageField = new DropdownField("言語"); languageField.RegisterValueChangedCallback(e => language = e.newValue); scroll.Add(languageField);
            voiceField = new DropdownField("音声"); voiceField.RegisterValueChangedCallback(e => voice = e.newValue); scroll.Add(voiceField);
            personaField = new DropdownField("人格"); personaField.RegisterValueChangedCallback(e => persona = e.newValue); scroll.Add(personaField);
            personaText = new TextField("カスタム人格") { multiline = true }; personaText.style.minHeight = 44; scroll.Add(personaText);
            applyButton = MakeButton("停止状態で設定を適用", ApplySettings); scroll.Add(applyButton);
            gain = new Slider("表示ゲイン", .1f, 3f); gain.RegisterValueChangedCallback(e => { if (neural != null) neural.DisplayGain = e.newValue; }); scroll.Add(gain);
            textInput = new TextField("文字で指示") { multiline = true }; textInput.maxLength = 2000; scroll.Add(textInput);
            sendButton = MakeButton("指示を送る", SendText); scroll.Add(sendButton);
            scroll.Add(Label("診断", 12, mint, FontStyle.Bold));
            var diagnosticText = new Label(); diagnosticText.name = "diagnostic-detail"; diagnosticText.style.whiteSpace = WhiteSpace.Normal; scroll.Add(diagnosticText);
            scroll.Add(Label("会話全文", 12, mint, FontStyle.Bold));
            transcriptLabel = new Label("会話の接続待ち"); transcriptLabel.style.whiteSpace = WhiteSpace.Normal; scroll.Add(transcriptLabel);
        }

        void Update()
        {
            if (!built || Time.unscaledTime < nextRefresh) return;
            nextRefresh = Time.unscaledTime + .1f;
            if (controller == null) BootstrapExistingController();
            Refresh(); UpdateGameImageRect();
        }

        void BootstrapExistingController()
        {
            if (controller == null) controller = FindFirstObjectByType<ConversationSessionController>();
            if (bootstrap == null) bootstrap = FindFirstObjectByType<ConversationNativeBootstrap>();
        }

        void Refresh()
        {
            if (neural != null)
            {
                neuralImage.image = neural.DisplayTexture;
                gain?.SetValueWithoutNotify(neural.DisplayGain);
                var observer = neural.Observer;
                if (observer == null) neuralStatus.text = "神経オブザーバー未接続";
                else
                {
                    string age = observer.FrameAgeMs < 0 ? "—" : observer.FrameAgeMs.ToString("0") + " ms";
                    string sample = observer.ObservedCount > 0 ? "観測 " + observer.ObservedCount + " / " + observer.PointCount : "観測データなし";
                    string firing = observer.IsFresh && observer.WindowMs > 0 ? "発火 " + observer.SpikeCount + " 回 / " + observer.WindowMs.ToString("0") + " ms · 活動細胞 " + observer.ActiveCount : "発火数: 有効な計測を待機";
                    neuralStatus.text = (observer.IsSchematic ? "模式配置・膜電位" : "細胞体座標") + " · " + observer.Mode + " / " + observer.Backend + "\n" + sample + " · " + firing + "\nseq " + observer.Sequence + " · age " + age + " · " + observer.State;
                }
            }
            if (controller == null)
            {
                SetActionAvailability(false);
                controlModeLabel.text = "操作状況: 停止中";
                actionFeedbackLabel.text = string.Empty;
                string bootstrapError = bootstrap == null ? null : bootstrap.StartupError;
                statusLabel.text = string.IsNullOrEmpty(bootstrapError) ? "起動中: 会話コントローラを待機中" : "起動エラー: " + bootstrapError;
                return;
            }
            string error = !string.IsNullOrEmpty(controller.Error) ? controller.Error : controller.AudioError;
            if (displayedSettingsRevision != controller.SettingsRevision && controller.Settings != null)
            {
                displayedSettingsRevision = controller.SettingsRevision;
                language = controller.Settings.language; voice = controller.Settings.voice; persona = controller.Settings.persona;
                personaText.SetValueWithoutNotify(controller.Settings.personaText ?? string.Empty);
            }
            statusLabel.text = !string.IsNullOrEmpty(error) ? "エラー: " + error : "接続: " + controller.Status + "  会話準備: " + controller.Ready + "  Brain ready: " + controller.BrainReady;
            string fullCaption = string.IsNullOrEmpty(controller.Caption) ? "会話の接続待ち" : controller.Caption;
            captionLabel.text = "字幕: " + RecentCaption(fullCaption);
            if (transcriptLabel != null) transcriptLabel.text = fullCaption;
            startButton.SetEnabled(controller.Ready && !controller.IsSessionRequested);
            stopButton.SetEnabled(controller.IsSessionRequested || controller.EnablingVoiceActions);
            settingsButton?.SetEnabled(true);
            settingsDrawer?.SetEnabled(true);
            voiceButton.text = controller.EnablingVoiceActions ? "音声操作：接続中" : controller.BodyControlActive ? "音声指示を待受中" : controller.ContinuousVoiceControl ? "音声操作：復旧中" : "声で操作を有効にする";
            voiceButton.SetEnabled(controller.Ready && controller.VoiceActionsAvailable && !controller.EnablingVoiceActions && !controller.BodyControlActive);
            string controlMode = controller.BodyControlActive ? "声で操作中" : controller.EnablingVoiceActions ? "停止中（声で操作の準備中）"
                : controller.ConversationLive && controller.ConversationInteraction == "chat_only" ? "会話のみ" : "停止中";
            controlModeLabel.text = "操作状況: " + controlMode;
            actionFeedbackLabel.text = string.IsNullOrEmpty(controller.ActionFeedback) ? string.Empty : "直近の操作案内: " + controller.ActionFeedback;
            muteButton.text = controller.MicrophoneMuted ? "マイクをオン" : "マイクをミュート";
            muteButton.SetEnabled(!controller.MicrophoneCaptureDisabled);
            volume?.SetValueWithoutNotify(controller.Volume);
            UpdateChoices(deviceField, controller.Devices, deviceField == null ? null : deviceField.value);
            UpdateChoices(languageField, controller.Options.languages, language);
            UpdateChoices(voiceField, controller.Options.voices, voice);
            UpdateChoices(personaField, controller.Options.personas, persona);
            applyButton?.SetEnabled(!controller.ConversationLive && controller.OutputInhibited);
            sendButton?.SetEnabled(controller.BodyControlActive);
            string factual = controller.MicrophoneMuted ? "マイクはミュート中" : controller.ReplyPlaying ? "音声を再生中" : controller.MicrophoneTransmitting ? "音声を送信中" : controller.ConversationLive ? "会話セッションは接続中" : "会話の接続待ち";
            string expression = controller.ReplyPlaying ? "発話中" : controller.MicrophoneTransmitting ? "聞いています" : controller.MicrophoneMuted ? "ミュート" : "待機";
            portraitSource.text = "表現の根拠: 会話状態（擬人化した表示）";
            portraitObservation.text = "気持ちはまだわかりません。事実: " + factual;
            portrait?.SetPresentation(expression, controller.InputRms > .01f ? .7f : .2f, Time.unscaledTime);
            DiagnosticsSummary = "status=" + controller.Status + "; ready=" + controller.Ready + "; brainReady=" + controller.BrainReady + "; backend=" + controller.Backend + "; sequence=" + controller.Sequence;
            diagnostics.text = DiagnosticsSummary;
            var detail = document.rootVisualElement.Q<Label>("diagnostic-detail");
            if (detail != null) detail.text = "Brain backend: " + controller.Backend + " / ready: " + controller.BrainReady + "\nframe age: " + controller.FrameAgeMs.ToString("0") + " ms / sequence: " + controller.Sequence + "\n" + (string.IsNullOrEmpty(controller.SchemaError) ? string.Empty : "schema: " + controller.SchemaError);
        }

        void ApplySettings() => controller?.ApplySettings(language, voice, persona, personaText == null ? string.Empty : personaText.value);
        void ToggleSettingsDrawer()
        {
            if (settingsDrawer == null) return;
            settingsOpen = !settingsOpen;
            settingsDrawer.style.display = settingsOpen ? DisplayStyle.Flex : DisplayStyle.None;
        }
        void SetActionAvailability(bool enabled)
        {
            startButton?.SetEnabled(enabled); stopButton?.SetEnabled(enabled); muteButton?.SetEnabled(enabled); voiceButton?.SetEnabled(enabled);
            applyButton?.SetEnabled(enabled); sendButton?.SetEnabled(enabled); settingsButton?.SetEnabled(enabled);
            if (settingsDrawer != null) settingsDrawer.SetEnabled(enabled);
        }
        static string RecentCaption(string value)
        {
            const int max = 240;
            value = value.Replace('\r', ' ').Replace('\n', ' ').Trim();
            return value.Length <= max ? value : "…" + value.Substring(value.Length - max);
        }
        static void UpdateChoices(DropdownField field, string[] choices, string selected)
        {
            if (field == null || choices == null || choices.Length == 0) return;
            field.choices = new List<string>(choices);
            if (field.choices.Contains(selected)) field.SetValueWithoutNotify(selected);
            else field.SetValueWithoutNotify(field.choices[0]);
        }
        void SendText() { if (controller == null || textInput == null) return; controller.SendPlayerText(textInput.value); textInput.value = string.Empty; }
        void RegisterControlSurface(VisualElement element)
        {
            element.RegisterCallback<PointerEnterEvent>(_ => pointerOverControls = true);
            element.RegisterCallback<PointerLeaveEvent>(_ => pointerOverControls = false);
        }
        void UpdateGameImageRect()
        {
            if (gameImage == null || gameTexture == null || gameImage.worldBound.width <= 0) { GameImageScreenRect = default; return; }
            Rect area = gameImage.worldBound; float textureRatio = (float)gameTexture.width / gameTexture.height; float areaRatio = area.width / area.height;
            if (textureRatio > areaRatio) { float h = area.width / textureRatio; GameImageScreenRect = new Rect(area.x, area.y + (area.height - h) * .5f, area.width, h); }
            else { float w = area.height * textureRatio; GameImageScreenRect = new Rect(area.x + (area.width - w) * .5f, area.y, w, area.height); }
        }
        VisualElement Card() { var e = new VisualElement(); e.style.backgroundColor = panel; e.style.borderTopLeftRadius = e.style.borderTopRightRadius = e.style.borderBottomLeftRadius = e.style.borderBottomRightRadius = 10; e.style.paddingLeft = e.style.paddingRight = 12; e.style.paddingTop = e.style.paddingBottom = 10; return e; }
        static VisualElement Row(string name) { return new VisualElement { name = name, style = { flexDirection = FlexDirection.Row } }; }
        static VisualElement Spacer() { return new VisualElement { style = { flexGrow = 1 } }; }
        Button MakeButton(string text, Action clicked)
        {
            var button = new Button(clicked) { text = text };
            button.style.backgroundColor = new Color(.12f, .19f, .25f);
            button.style.color = cream;
            button.style.borderTopLeftRadius = button.style.borderTopRightRadius = button.style.borderBottomLeftRadius = button.style.borderBottomRightRadius = 5;
            button.style.paddingLeft = button.style.paddingRight = 14;
            button.style.paddingTop = button.style.paddingBottom = 10;
            button.RegisterCallback<MouseEnterEvent>(_ => { if (button.enabledInHierarchy) button.style.opacity = .8f; });
            button.RegisterCallback<MouseLeaveEvent>(_ => button.style.opacity = 1);
            return button;
        }
        static Label Label(string value, int size, Color color, FontStyle style = FontStyle.Normal) { return new Label(value) { style = { fontSize = size, color = color, unityFontStyleAndWeight = style } }; }
        static Font JapaneseFont() => Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic UI", "Meiryo", "Arial" }, 16);
        void OnDestroy()
        {
            if (document != null) { document.panelSettings = null; Destroy(document); }
            if (uiFont != null) Destroy(uiFont);
            if (panelSettings != null) Destroy(panelSettings);
        }
    }
}
