using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Flylingual.BlindSugarRun;
using Flylingual.PlayScreen;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Flylingual.Conversation
{
    // Explicit real Player probe; never supplies a Brain frame or motor value.
    public sealed class NeuralFeedbackProbe : MonoBehaviour
    {
        string output, originalLanguage;
        bool english;
        int questionIndex;
        ConversationSessionController controller;
        readonly HashSet<long> frames = new HashSet<long>();
        readonly HashSet<string> observations = new HashSet<string>();
        readonly List<float> frameMs = new List<float>();
        StreamWriter events;
        [Serializable] sealed class Result
        {
            public string result = "startup_timeout", backend, error, language;
            public bool live, brainReady, fresh, stopped, neuralAvailable;
            public int frames, neuralFrames, correlatedBodyFrames;
            public long firstSequence, lastSequence;
            public float displacement, unityFrameP95Ms;
            public string brainEndpoint = "127.0.0.1:18766";
            public string input = "explicit synthetic text; real GPT-Live/API/Brain/Unity; no microphone claim";
            public string[] questionReplies;
        }
        Result result = new Result();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, "-neuralFeedbackProbe");
            if (i < 0 || i + 1 >= args.Length || FindAnyObjectByType<NeuralFeedbackProbe>() != null) return;
            var go = new GameObject("Neural feedback real Player probe"); DontDestroyOnLoad(go);
            var probe = go.AddComponent<NeuralFeedbackProbe>();
            probe.output = Path.GetFullPath(args[i + 1]);
            probe.english = Array.IndexOf(args, "-neuralFeedbackEnglish") >= 0;
            int q = Array.IndexOf(args, "-neuralFeedbackQuestion");
            if (q >= 0 && q + 1 < args.Length && int.TryParse(args[q + 1], out int selected))
                probe.questionIndex = Mathf.Clamp(selected, 0, 3);
            probe.originalLanguage = GameLanguage.Code;
            GameLanguage.SetLanguage(probe.english ? "en" : "ja");
        }

        void Update()
        {
            if (controller == null || !controller.HasFreshBrain) return;
            frames.Add(controller.Sequence); frameMs.Add(Time.unscaledDeltaTime * 1000);
            var observation = controller.NeuralResponse;
            if (observation != null && observation.fresh && observations.Add(observation.sequence))
            {
                if (observation.body != null && observation.body.fresh && observation.body.correlated)
                    result.correlatedBodyFrames++;
            }
        }
        void Capture(string json)
        {
            // This opt-in artifact contains fixture dialogue, no audio or credentials.
            if (json.StartsWith("{\"type\": \"neural_response\"") || json.Contains("\"type\":\"neural_response\"")
                || json.Contains("\"type\": \"command_result\"") || json.Contains("\"type\": \"conversation_text\""))
                events?.WriteLine(json);
        }
        IEnumerator Start()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            events = new StreamWriter(output + ".events.jsonl"); events.AutoFlush = true;
            yield return null;
            if (SceneManager.GetActiveScene().path != TitleScreen.InGameScenePath)
                yield return SceneManager.LoadSceneAsync(TitleScreen.InGameScenePath);
            // Follow the real title/start flow, including a first-run tutorial.
            // SendMessage also supports the earlier private button callback.
            var title = FindAnyObjectByType<TitleScreen>();
            if (title != null) title.SendMessage("StartGame", SendMessageOptions.DontRequireReceiver);
            yield return null;
            title = FindAnyObjectByType<TitleScreen>();
            if (title != null) title.SendMessage("StartGame", SendMessageOptions.DontRequireReceiver);
            BlindSugarRunSession stage = null;
            float deadline = Time.realtimeSinceStartup + 120;
            while (Time.realtimeSinceStartup < deadline)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                stage = FindAnyObjectByType<BlindSugarRunSession>();
                if (controller != null && controller.BodyControlActive && stage != null && stage.fly != null) break;
                yield return new WaitForSecondsRealtime(.2f);
            }
            if (controller != null && controller.BodyControlActive && stage != null && stage.fly != null)
            {
                controller.ControlEventReceived += Capture;
                result.live = controller.ConversationLive; result.backend = controller.Backend;
                result.brainReady = controller.BrainReady; result.language = controller.Settings.language;
                result.firstSequence = controller.Sequence;
                controller.SendPlayerText(english ? "Stop" : "止まって");
                yield return new WaitForSecondsRealtime(2);
                Vector3 initial = stage.fly.Position;
                controller.SendPlayerText(english ? "Move forward" : "前に進んで");
                yield return new WaitForSecondsRealtime(3);
                result.displacement = Vector3.Distance(initial, stage.fly.Position);
                controller.SendPlayerText(english ? "Stop" : "止まって");
                yield return new WaitForSecondsRealtime(2);
                result.stopped = controller.LastAppliedAction == "STOP";
                ScreenCapture.CaptureScreenshot(output + ".png");
                string[] questions = english ? new[] { "What state are you in now?", "Did you refuse because you were afraid?", "Less commentary and no sarcasm, please.", "Tell me a little about space." }
                    : new[] { "今どういう状態？", "怖くて動きを拒否したの？", "実況を減らして、皮肉はやめて。", "宇宙について少し教えて。" };
                var replies = new List<string>();
                // One complete question per run keeps the real 20-second
                // stationary penalty active without altering the game rules.
                foreach (string question in new[] { questions[questionIndex] })
                {
                    string before = controller.Caption;
                    controller.SendPlayerText(question);
                    yield return new WaitForSecondsRealtime(11);
                    string after = controller.Caption;
                    replies.Add(after.StartsWith(before) ? after.Substring(before.Length) : after);
                }
                result.questionReplies = replies.ToArray();
                result.frames = frames.Count; result.neuralFrames = observations.Count;
                result.lastSequence = controller.Sequence; result.fresh = controller.HasFreshBrain;
                result.neuralAvailable = controller.NeuralResponseAvailable;
                result.error = controller.Error;
                frameMs.Sort();
                result.unityFrameP95Ms = frameMs.Count == 0 ? 0 : frameMs[(int)((frameMs.Count - 1) * .95f)];
                result.result = result.live && result.fresh && result.stopped && result.frames >= 30 && result.displacement > .05f ? "control_pass" : "control_failed";
                controller.ControlEventReceived -= Capture;
            }
            else if (controller != null) result.error = controller.Error;
            events.Dispose(); events = null;
            File.WriteAllText(output, JsonUtility.ToJson(result, true));
            if (controller != null) controller.EmergencyStop();
            GameLanguage.SetLanguage(originalLanguage);
            yield return new WaitForSecondsRealtime(1);
            Application.Quit();
        }
        void OnDestroy() { events?.Dispose(); }
    }
}
