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
        NeuralResponsePanel neuralResponse;
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
        readonly List<Action> localizedText = new List<Action>();
        string displayedLanguage;
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
            var subtitle = LocalizedLabel("ハエと話し、行動と神経活動を観察する", "Talk to a fly and observe its actions and neural activity", 14, cream); subtitle.style.marginLeft = 16; subtitle.style.opacity = .82f; header.Add(subtitle);
            header.Add(Spacer()); statusLabel = LocalizedLabel("接続を確認中", "Checking connection", 13, mint); statusLabel.style.unityTextAlign = TextAnchor.MiddleRight; header.Add(statusLabel); root.Add(header);

            var main = Row("main"); main.style.flexGrow = 1; main.style.minHeight = 260; main.style.marginBottom = 12; root.Add(main);
            gameFrame = Card(); gameFrame.style.flexGrow = 7; gameFrame.style.flexBasis = 0; gameFrame.style.marginRight = 12; main.Add(gameFrame);
            var gameTitle = LocalizedLabel("ゲーム画面 / GAME VIEW", "GAME VIEW", 13, amber, FontStyle.Bold); gameTitle.style.marginLeft = 14; gameTitle.style.marginTop = 12; gameFrame.Add(gameTitle);
            gameImage = new Image { scaleMode = ScaleMode.ScaleToFit }; gameImage.style.flexGrow = 1; gameImage.style.marginLeft = gameImage.style.marginRight = 10; gameImage.style.marginBottom = 10; gameFrame.Add(gameImage);
            blindMessage = LocalizedLabel("BLIND SUGAR RUN\n\n声を頼りに、砂糖を探そう。\nたどり着いたら、歩いてきた世界が見える。", "BLIND SUGAR RUN\n\nUse your voice to find the sugar.\nReach it to reveal the world you explored.", 22, cream);
            blindMessage.style.flexGrow = 1; blindMessage.style.unityTextAlign = TextAnchor.MiddleCenter;
            blindMessage.style.whiteSpace = WhiteSpace.Normal; blindMessage.style.display = DisplayStyle.None; gameFrame.Add(blindMessage);
            gameFrame.RegisterCallback<GeometryChangedEvent>(_ => UpdateGameImageRect());

            var side = new VisualElement(); side.style.flexGrow = 3; side.style.flexBasis = 0; side.style.minWidth = 260; side.style.flexDirection = FlexDirection.Column; main.Add(side);
            var neuralCard = Card(); neuralCard.style.flexGrow = 2; neuralCard.style.flexBasis = 0; neuralCard.style.marginBottom = 12; side.Add(neuralCard);
            var neuralTitle = LocalizedLabel("脳・神経活動", "Brain activity", 13, mint, FontStyle.Bold);
            BindText(value => neuralTitle.tooltip = value, "橙色は実測発火と短い残光。シアン・紫は起動時の基準からの平均膜電位変化で、発火とは別です。膜電位は受信した細胞だけを表示します。灰色は細胞の位置です。", "Orange shows observed spikes with a short afterglow. Cyan and purple show mean membrane potential changes from the startup baseline, separately from spikes. Voltage is shown only for received cells. Gray marks cell positions.");
            neuralCard.Add(neuralTitle);
            var neuralLegend = Row("neural-legend"); neuralLegend.style.flexWrap = Wrap.Wrap;
            neuralLegend.Add(LocalizedLabel("● 発火  ", "● Spikes  ", 12, new Color(1f, .48f, .12f)));
            neuralLegend.Add(LocalizedLabel("● 電位上昇  ", "● Voltage rise  ", 12, new Color(.1f, .85f, 1f)));
            neuralLegend.Add(LocalizedLabel("● 電位低下", "● Voltage fall", 12, new Color(.76f, .38f, 1f)));
            localizedText.Add(() => neuralLegend.tooltip = neuralTitle.tooltip); neuralLegend.tooltip = neuralTitle.tooltip; neuralCard.Add(neuralLegend);
            neuralImage = new Image { scaleMode = ScaleMode.ScaleToFit }; neuralImage.style.flexGrow = 1; neuralImage.style.minHeight = 90; neuralImage.style.marginTop = 7; neuralCard.Add(neuralImage);
            neuralStatus = LocalizedLabel("可視化データを待機中", "Waiting for visualization data", 12, cream); neuralStatus.style.opacity = .8f; neuralStatus.style.whiteSpace = WhiteSpace.Normal; neuralCard.Add(neuralStatus);
            RegisterControlSurface(neuralCard);
            neuralResponse = new NeuralResponsePanel(); neuralCard.Add(neuralResponse);
            neuralImage.RegisterCallback<PointerMoveEvent>(evt => { if (evt.pressedButtons != 0 && neural != null) neural.Rotate(evt.deltaPosition); });
            neuralImage.RegisterCallback<WheelEvent>(evt => { if (neural != null) { neural.Zoom(evt.delta.y); evt.StopPropagation(); } });

            var portraitCard = Card(); portraitCard.style.flexGrow = 1; portraitCard.style.flexBasis = 0; side.Add(portraitCard);
            portraitCard.Add(LocalizedLabel("ハエリンガル / FLYLINGUAL", "FLYLINGUAL", 13, amber, FontStyle.Bold));
            portrait = new FlyPortraitElement(); portrait.style.flexGrow = 1; portrait.style.minHeight = 96; portraitCard.Add(portrait);
            portraitSource = LocalizedLabel("表現の根拠: 接続状態", "Expression source: connection state", 12, mint); portraitCard.Add(portraitSource);
            portraitObservation = LocalizedLabel("気持ちはまだわかりません", "Feelings are not yet known", 12, cream); portraitObservation.style.whiteSpace = WhiteSpace.Normal; portraitCard.Add(portraitObservation);

            var controls = Card(); controls.style.flexShrink = 0; controls.style.paddingTop = 9; controls.style.paddingBottom = 9; root.Add(controls); RegisterControlSurface(controls);
            var actions = Row("actions"); actions.style.alignItems = Align.Center; actions.style.flexWrap = Wrap.Wrap; controls.Add(actions);
            startButton = LocalizedButton("会話のみ開始", "Start chat only", () => controller?.StartConversation()); actions.Add(startButton);
            stopButton = LocalizedButton("会話を終了", "End conversation", () => controller?.StopConversation()); actions.Add(stopButton);
            var emergency = LocalizedButton("緊急停止", "Emergency stop", () => controller?.EmergencyStop()); emergency.style.backgroundColor = new Color(.64f, .18f, .13f); emergency.style.color = Color.white; emergency.style.unityFontStyleAndWeight = FontStyle.Bold; actions.Add(emergency);
            muteButton = LocalizedButton("マイクをミュート", "Mute microphone", () => { if (controller != null) controller.SetMicrophoneMuted(!controller.MicrophoneMuted); }); actions.Add(muteButton);
            voiceButton = LocalizedButton("声で操作を有効にする", "Enable voice controls", () => controller?.EnableVoiceActions()); actions.Add(voiceButton);
            actions.Add(Spacer()); settingsButton = LocalizedButton("設定と診断", "Settings and diagnostics", ToggleSettingsDrawer); actions.Add(settingsButton);
            controlModeLabel = LocalizedLabel("操作状況: 停止中", "Controls: stopped", 13, mint, FontStyle.Bold); controlModeLabel.style.marginTop = 5; controls.Add(controlModeLabel);
            actionFeedbackLabel = Label(string.Empty, 13, cream); actionFeedbackLabel.style.whiteSpace = WhiteSpace.Normal; controls.Add(actionFeedbackLabel);
            captionLabel = LocalizedLabel("字幕: 接続待ち", "Captions: waiting for connection", 14, cream); captionLabel.style.marginTop = 7; captionLabel.style.whiteSpace = WhiteSpace.Normal; captionLabel.style.maxHeight = 42; captionLabel.style.overflow = Overflow.Hidden; controls.Add(captionLabel);
            diagnostics = Label(string.Empty, 11, cream); diagnostics.style.opacity = .66f; diagnostics.style.display = DisplayStyle.None; controls.Add(diagnostics);
            settingsDrawer = Card(); settingsDrawer.style.position = Position.Absolute; settingsDrawer.style.right = 16; settingsDrawer.style.bottom = 96; settingsDrawer.style.width = 430; settingsDrawer.style.maxHeight = 360; settingsDrawer.style.display = DisplayStyle.None; root.Add(settingsDrawer); RegisterControlSurface(settingsDrawer);
            settingsDrawer.style.backgroundColor = new Color(.055f, .086f, .125f, 1f);
            settingsDrawer.style.borderTopWidth = settingsDrawer.style.borderBottomWidth = settingsDrawer.style.borderLeftWidth = settingsDrawer.style.borderRightWidth = 1;
            settingsDrawer.style.borderTopColor = settingsDrawer.style.borderBottomColor = settingsDrawer.style.borderLeftColor = settingsDrawer.style.borderRightColor = mint;
            BuildSettings(settingsDrawer);
            displayedLanguage = GameLanguage.Code;
            built = true;
            BootstrapExistingController();
            SetActionAvailability(false);
            SetGameTexture(gameTexture);
        }

        void BuildSettings(VisualElement settings)
        {
            var scroll = new ScrollView(ScrollViewMode.Vertical); scroll.style.maxHeight = 300; settings.Add(scroll);
            scroll.Add(LocalizedLabel("マイク入力と出力", "Microphone and audio", 12, mint, FontStyle.Bold));
            deviceField = new DropdownField(GameLanguage.Text("マイク", "Microphone")); deviceField.RegisterValueChangedCallback(e => controller?.SetMicrophoneDevice(e.newValue)); scroll.Add(deviceField);
            volume = new Slider(GameLanguage.Text("音量", "Volume"), 0, 1); volume.RegisterValueChangedCallback(e => controller?.SetVolume(e.newValue)); scroll.Add(volume);
            languageField = new DropdownField(GameLanguage.Text("言語", "Language")); languageField.RegisterValueChangedCallback(e => language = e.newValue); scroll.Add(languageField);
            voiceField = new DropdownField(GameLanguage.Text("音声", "Voice")); voiceField.RegisterValueChangedCallback(e => voice = e.newValue); scroll.Add(voiceField);
            personaField = new DropdownField(GameLanguage.Text("人格", "Personality")); personaField.RegisterValueChangedCallback(e => persona = e.newValue); scroll.Add(personaField);
            personaText = new TextField(GameLanguage.Text("カスタム人格", "Custom personality")) { multiline = true }; personaText.style.minHeight = 44; scroll.Add(personaText);
            applyButton = LocalizedButton("停止状態で設定を適用", "Apply settings while stopped", ApplySettings); scroll.Add(applyButton);
            gain = new Slider(GameLanguage.Text("表示ゲイン", "Display gain"), .1f, 3f); gain.RegisterValueChangedCallback(e => { if (neural != null) neural.DisplayGain = e.newValue; }); scroll.Add(gain);
            textInput = new TextField(GameLanguage.Text("文字で指示", "Type a command")) { multiline = true }; textInput.maxLength = 2000; scroll.Add(textInput);
            sendButton = LocalizedButton("指示を送る", "Send command", SendText); scroll.Add(sendButton);
            scroll.Add(LocalizedLabel("診断", "Diagnostics", 12, mint, FontStyle.Bold));
            BindText(value => deviceField.label = value, "マイク", "Microphone");
            BindText(value => volume.label = value, "音量", "Volume");
            BindText(value => languageField.label = value, "言語", "Language");
            BindText(value => voiceField.label = value, "音声", "Voice");
            BindText(value => personaField.label = value, "人格", "Personality");
            BindText(value => personaText.label = value, "カスタム人格", "Custom personality");
            BindText(value => gain.label = value, "表示ゲイン", "Display gain");
            BindText(value => textInput.label = value, "文字で指示", "Type a command");
            var diagnosticText = new Label(); diagnosticText.name = "diagnostic-detail"; diagnosticText.style.whiteSpace = WhiteSpace.Normal; scroll.Add(diagnosticText);
            scroll.Add(LocalizedLabel("会話全文", "Conversation transcript", 12, mint, FontStyle.Bold));
            transcriptLabel = LocalizedLabel("会話の接続待ち", "Waiting for conversation", 16, cream); transcriptLabel.style.whiteSpace = WhiteSpace.Normal; scroll.Add(transcriptLabel);
        }

        void Update()
        {
            if (!built || Time.unscaledTime < nextRefresh) return;
            nextRefresh = Time.unscaledTime + .1f;
            if (displayedLanguage != GameLanguage.Code)
            {
                displayedLanguage = GameLanguage.Code;
                foreach (Action refreshText in localizedText) refreshText();
            }
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
            neuralResponse?.Refresh(controller);
            if (neural != null)
            {
                neuralImage.image = neural.DisplayTexture;
                gain?.SetValueWithoutNotify(neural.DisplayGain);
                var observer = neural.Observer;
                if (observer == null) neuralStatus.text = GameLanguage.Text("神経オブザーバー未接続", "Neural observer disconnected");
                else
                {
                    string age = observer.FrameAgeMs < 0 ? "—" : observer.FrameAgeMs.ToString("0") + " ms";
                    string firing = observer.IsFresh && observer.WindowMs > 0 ? GameLanguage.Text("発火 ", "Spikes: ") + observer.ActiveCount + GameLanguage.Text("細胞 · ", " cells · ") + observer.SpikeCount + GameLanguage.Text("回 / ", " spikes / ") + observer.WindowMs.ToString("0") + "ms" : GameLanguage.Text("発火数: 有効な計測を待機", "Spikes: waiting for valid measurements");
                    string voltage = observer.IsFresh ? GameLanguage.Text("膜電位: ", "Membrane potential: ") + observer.VoltageObservedCount + GameLanguage.Text("細胞を観測 · 変化 ", " cells observed · changed: ") + (observer.PositiveVoltageCount + observer.NegativeVoltageCount) : GameLanguage.Text("膜電位: 有効な計測を待機", "Membrane potential: waiting for valid measurements");
                    neuralStatus.text = firing + "\n" + voltage + "\n" + observer.Mode + " · " + (observer.IsFresh ? GameLanguage.Text("受信中", "Receiving") : observer.State);
                    neuralStatus.tooltip = GameLanguage.Text("表示対象 ", "Displayed: ") + observer.ObservedCount + " / " + observer.PointCount + " · " + observer.Backend + " · seq " + observer.Sequence + " · age " + age + GameLanguage.Text("\n膜電位の色は基準との差を強調表示。変化細胞数は±0.001mVを超えた細胞です。", "\nVoltage colors emphasize changes from baseline. Changed cells differ by more than ±0.001mV.");
                }
            }
            if (controller == null)
            {
                SetActionAvailability(false);
                controlModeLabel.text = GameLanguage.Text("操作状況: 停止中", "Controls: stopped");
                actionFeedbackLabel.text = string.Empty;
                string bootstrapError = bootstrap == null ? null : bootstrap.StartupError;
                statusLabel.text = string.IsNullOrEmpty(bootstrapError) ? GameLanguage.Text("起動中: 会話コントローラを待機中", "Starting: waiting for conversation controller") : GameLanguage.Text("起動エラー: ", "Startup error: ") + bootstrapError;
                return;
            }
            string error = !string.IsNullOrEmpty(controller.Error) ? controller.Error : controller.AudioError;
            if (displayedSettingsRevision != controller.SettingsRevision && controller.Settings != null)
            {
                displayedSettingsRevision = controller.SettingsRevision;
                language = controller.Settings.language; voice = controller.Settings.voice; persona = controller.Settings.persona;
                personaText.SetValueWithoutNotify(controller.Settings.personaText ?? string.Empty);
            }
            statusLabel.text = !string.IsNullOrEmpty(error) ? GameLanguage.Text("エラー: ", "Error: ") + error : GameLanguage.Text("接続: ", "Connection: ") + controller.Status + GameLanguage.Text("  会話準備: ", "  Conversation ready: ") + controller.Ready + "  Brain ready: " + controller.BrainReady;
            string fullCaption = string.IsNullOrEmpty(controller.Caption) ? GameLanguage.Text("会話の接続待ち", "Waiting for conversation") : controller.Caption;
            captionLabel.text = GameLanguage.Text("字幕: ", "Captions: ") + RecentCaption(fullCaption);
            if (transcriptLabel != null) transcriptLabel.text = fullCaption;
            startButton.SetEnabled(controller.Ready && !controller.IsSessionRequested);
            stopButton.SetEnabled(controller.IsSessionRequested || controller.EnablingVoiceActions);
            settingsButton?.SetEnabled(true);
            settingsDrawer?.SetEnabled(true);
            voiceButton.text = controller.TextConversation ? GameLanguage.Text("テキスト指示を待受中", "Ready for text commands") : controller.EnablingVoiceActions ? GameLanguage.Text("音声操作：接続中", "Voice controls: connecting") : controller.BodyControlActive ? GameLanguage.Text("音声指示を待受中", "Listening for voice commands") : controller.ContinuousVoiceControl ? GameLanguage.Text("音声操作：復旧中", "Voice controls: reconnecting") : GameLanguage.Text("声で操作を有効にする", "Enable voice controls");
            voiceButton.SetEnabled(controller.Ready && controller.VoiceActionsAvailable && !controller.EnablingVoiceActions && !controller.BodyControlActive);
            string controlMode = controller.TextConversation && controller.BodyControlActive ? GameLanguage.Text("テキストで操作中", "Text controls active") : controller.BodyControlActive ? GameLanguage.Text("声で操作中", "Voice controls active") : controller.EnablingVoiceActions ? GameLanguage.Text("停止中（声で操作の準備中）", "Stopped (preparing voice controls)")
                : controller.ConversationActive && controller.ConversationInteraction == "chat_only" ? GameLanguage.Text("会話のみ", "Chat only") : GameLanguage.Text("停止中", "Stopped");
            controlModeLabel.text = GameLanguage.Text("操作状況: ", "Controls: ") + controlMode;
            var execution = controller.ActiveExecution;
            if (controller.BodyControlActive && execution != null && execution.executionMode == "distance")
            {
                controlModeLabel.text += GameLanguage.Text(" · 距離 ", " · Distance: ") + execution.traveledMeters.ToString("0.00") + " / " + execution.targetDistanceMeters.ToString("0.##") + "m";
                if (execution.distancePhase == "braking") controlModeLabel.text += GameLanguage.Text("（停止を確認中）", " (confirming stop)");
            }
            actionFeedbackLabel.text = string.IsNullOrEmpty(controller.ActionFeedback) ? string.Empty : GameLanguage.Text("直近の操作案内: ", "Latest control feedback: ") + controller.ActionFeedback;
            muteButton.text = controller.MicrophoneMuted ? GameLanguage.Text("マイクをオン", "Unmute microphone") : GameLanguage.Text("マイクをミュート", "Mute microphone");
            muteButton.SetEnabled(!controller.TextConversation && !controller.MicrophoneCaptureDisabled);
            deviceField?.SetEnabled(!controller.TextConversation);
            voiceField?.SetEnabled(!controller.TextConversation);
            volume?.SetValueWithoutNotify(controller.Volume);
            UpdateChoices(deviceField, controller.Devices, deviceField == null ? null : deviceField.value);
            UpdateChoices(languageField, controller.Options.languages, language);
            UpdateChoices(voiceField, controller.Options.voices, voice);
            UpdateChoices(personaField, controller.Options.personas, persona);
            applyButton?.SetEnabled(!controller.ConversationActive && controller.OutputInhibited);
            sendButton?.SetEnabled(controller.BodyControlActive);
            string factual = controller.TextConversation ? GameLanguage.Text("テキスト指示を入力して送信", "Type and send a command") : controller.MicrophoneMuted ? GameLanguage.Text("マイクはミュート中", "Microphone muted") : controller.ReplyPlaying ? GameLanguage.Text("音声を再生中", "Playing speech") : controller.MicrophoneTransmitting ? GameLanguage.Text("音声を送信中", "Sending audio") : controller.ConversationActive ? GameLanguage.Text("会話セッションは接続中", "Conversation connected") : GameLanguage.Text("会話の接続待ち", "Waiting for conversation");
            string expression = controller.ReplyPlaying ? GameLanguage.Text("発話中", "Speaking") : controller.MicrophoneTransmitting ? GameLanguage.Text("聞いています", "Listening") : controller.MicrophoneMuted ? GameLanguage.Text("ミュート", "Muted") : GameLanguage.Text("待機", "Waiting");
            portraitSource.text = GameLanguage.Text("表現の根拠: 会話状態（擬人化した表示）", "Expression source: conversation state (personified display)");
            portraitObservation.text = GameLanguage.Text("気持ちはまだわかりません。事実: ", "Feelings are not yet known. Observed: ") + factual;
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
        // Update text in place so changing the UI language never rebuilds inputs or discards edits.
        void BindText(Action<string> setter, string ja, string en)
        {
            Action refresh = () => setter(GameLanguage.Text(ja, en));
            localizedText.Add(refresh);
            refresh();
        }
        Label LocalizedLabel(string ja, string en, int size, Color color, FontStyle style = FontStyle.Normal)
        {
            Label label = Label(string.Empty, size, color, style);
            BindText(value => label.text = value, ja, en);
            return label;
        }
        Button LocalizedButton(string ja, string en, Action clicked)
        {
            Button button = MakeButton(string.Empty, clicked);
            BindText(value => button.text = value, ja, en);
            return button;
        }
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
