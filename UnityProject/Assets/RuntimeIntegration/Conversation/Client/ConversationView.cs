using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Runtime-only IMGUI view: no UXML, UIDocument, or scene asset dependency.</summary>
    public sealed class ConversationView : MonoBehaviour
    {
        const int WindowId = 748193;
        public ConversationSessionController Controller { get; set; }
        Rect panel = new Rect(18f, 18f, 420f, 360f);
        Vector2 scroll;
        bool expanded, spaceHeld, mouseHeld;
        GUISkin skin;
        int deviceIndex;
        string language = "ja", voice = "marin", persona = "friendly", personaText = "";

        void Awake() { if (Controller == null) Controller = GetComponent<ConversationSessionController>(); }
        void Update() { if (Controller != null) Controller.SetPushToTalk(spaceHeld || mouseHeld); }
        void OnApplicationFocus(bool focused) { if (!focused) { spaceHeld = mouseHeld = false; } }

        void OnGUI()
        {
            if (Controller == null) return;
            if (skin == null)
            {
                skin = Instantiate(GUI.skin);
                skin.font = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic UI", "Meiryo", "Arial" }, 16);
                skin.label.fontSize = skin.button.fontSize = skin.toggle.fontSize = skin.textField.fontSize = 16;
                skin.label.wordWrap = true;
            }
            var previousSkin = GUI.skin;
            GUI.skin = skin;
            float scale = Mathf.Max(1f, Screen.dpi > 0f ? Screen.dpi / 120f : 1f);
            GUI.matrix = Matrix4x4.Scale(new Vector3(scale, scale, 1f));
            panel.width = Mathf.Min(560f / scale, Screen.width / scale - 20f);
            panel.height = Mathf.Min(expanded ? 620f / scale : 390f / scale, Screen.height / scale - 20f);
            panel = GUI.Window(WindowId, panel, Draw, "Flylingual 会話");
            GUI.matrix = Matrix4x4.identity;
            GUI.skin = previousSkin;
        }

        void Draw(int id)
        {
            scroll = GUILayout.BeginScrollView(scroll);
            GUILayout.Label("接続: " + Controller.Status + "  準備: " + Controller.Ready);
            GUILayout.Label("会話: " + Controller.ConversationInteraction + "  所有者: " + Controller.Owner + "  出力抑止: " + Controller.OutputInhibited);
            GUILayout.Label("世代: " + Controller.ConversationGeneration + "  送信待ち: " + Controller.SendQueueDepth);
            if (!string.IsNullOrEmpty(Controller.Error)) GUILayout.Label("エラー: " + Controller.Error);
            GUILayout.BeginHorizontal();
            GUI.enabled = Controller.Ready && !Controller.IsSessionRequested;
            if (GUILayout.Button("会話を開始")) Controller.StartConversation();
            GUI.enabled = Controller.IsSessionRequested;
            if (GUILayout.Button("会話を終了")) Controller.StopConversation();
            GUI.enabled = true;
            if (GUILayout.Button("身体を停止")) Controller.EmergencyStop();
            GUILayout.EndHorizontal();
            Rect pttRect = GUILayoutUtility.GetRect(new GUIContent("押して話す (Space)"), GUI.skin.button, GUILayout.Height(30f));
            Event e = Event.current;
            if (e.type == EventType.MouseDown && pttRect.Contains(e.mousePosition)) { mouseHeld = true; e.Use(); }
            if (e.type == EventType.MouseUp && mouseHeld) { mouseHeld = false; e.Use(); }
            if (e.type == EventType.KeyDown && e.keyCode == KeyCode.Space) { spaceHeld = true; e.Use(); }
            if (e.type == EventType.KeyUp && e.keyCode == KeyCode.Space) { spaceHeld = false; e.Use(); }
            GUI.Button(pttRect, mouseHeld || spaceHeld ? "話しています…" : "押して話す (Space)");
            GUILayout.Label("字幕: " + Controller.Caption);
            GUILayout.Label("マイク RMS: " + Controller.InputRms.ToString("F3") + " @ " + Controller.SampleRate + " Hz / 返信: " + Controller.BufferedMilliseconds + " ms");
            GUILayout.Label("再生 samples: " + Controller.PlayedSamples + "  underruns: " + Controller.Underruns);
            Controller.SetVolume(GUILayout.HorizontalSlider(Controller.Volume, 0f, 1f));
            if (!string.IsNullOrEmpty(Controller.AudioError)) GUILayout.Label("音声: " + Controller.AudioError);
            expanded = GUILayout.Toggle(expanded, "設定と診断");
            if (expanded) DrawSettings();
            GUILayout.EndScrollView();
            GUI.DragWindow(new Rect(0f, 0f, 10000f, 20f));
        }

        void DrawSettings()
        {
            var devices = Controller.Devices;
            if (devices.Length > 0)
            {
                deviceIndex = Mathf.Clamp(deviceIndex, 0, devices.Length - 1);
                deviceIndex = GUILayout.SelectionGrid(deviceIndex, devices, 1);
                Controller.SetMicrophoneDevice(devices[deviceIndex]);
            }
            else GUILayout.Label("マイク: デバイスなし");
            language = SelectOrText("言語", language, Controller.Options.languages);
            voice = SelectOrText("音声", voice, Controller.Options.voices);
            persona = SelectOrText("人格", persona, Controller.Options.personas);
            GUILayout.Label("カスタム人格"); personaText = GUILayout.TextArea(personaText, GUILayout.MinHeight(42f));
            GUI.enabled = !Controller.ConversationLive && Controller.OutputInhibited;
            if (GUILayout.Button("停止状態で設定を適用")) Controller.ApplySettings(language, voice, persona, personaText);
            GUI.enabled = true;
            GUILayout.Label("Brain backend: " + Controller.Backend + "  ready: " + Controller.BrainReady);
            GUILayout.Label("frame age: " + Controller.FrameAgeMs + " ms  sequence: " + Controller.Sequence);
            if (!string.IsNullOrEmpty(Controller.SchemaError)) GUILayout.Label("schema: " + Controller.SchemaError);
        }

        static string SelectOrText(string label, string current, string[] options)
        {
            GUILayout.Label(label);
            if (options != null && options.Length > 0)
            {
                int selected = System.Array.IndexOf(options, current);
                selected = GUILayout.SelectionGrid(Mathf.Max(0, selected), options, Mathf.Min(3, options.Length));
                return options[selected];
            }
            return GUILayout.TextField(current);
        }
        void OnDisable() { spaceHeld = mouseHeld = false; Controller?.SetPushToTalk(false); }
        void OnDestroy() { if (skin != null) { Destroy(skin.font); Destroy(skin); } }
    }
}
