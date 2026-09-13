using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using FlyBrainVisualization;
using Flylingual.Conversation;
using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.PlayScreen
{
    /// <summary>Explicit visual acceptance recorder. Observes the same real local session as the UI.</summary>
    public sealed class PlayScreenProbe : MonoBehaviour
    {
        [Serializable] sealed class Sample
        {
            public float time;
            public string backend, mode, state, dataset, error;
            public bool ready, fresh, schematic, outputInhibited;
            public long sequence, spikes;
            public int observed, pointCount;
            public double ageMs;
        }
        [Serializable] sealed class Report
        {
            public string endpoint = "127.0.0.1:18766", unity;
            public int width, height;
            public bool uiBuilt, gameTexture, neuralTexture, emergencyVisible, settingsOpened, settingsClosed;
            public List<Sample> samples = new List<Sample>();
        }
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (!string.IsNullOrEmpty(FlyVisualDemo.WindowsReplayDemo.Argument("-playScreenProbe")))
                new GameObject("Play Screen Acceptance Recorder").AddComponent<PlayScreenProbe>();
        }
        IEnumerator Start()
        {
            string directory = Path.GetFullPath(FlyVisualDemo.WindowsReplayDemo.Argument("-playScreenProbe"));
            Directory.CreateDirectory(directory);
            var report = new Report { width = Screen.width, height = Screen.height, unity = Application.unityVersion };
            float until = Time.realtimeSinceStartup + 65;
            PlayScreenView view = null; ConversationSessionController controller = null;
            while (Time.realtimeSinceStartup < until)
            {
                view = FindFirstObjectByType<PlayScreenView>(); controller = FindFirstObjectByType<ConversationSessionController>();
                if (view != null && view.IsBuilt && controller != null && controller.Ready) break;
                yield return new WaitForSecondsRealtime(.2f);
            }
            report.uiBuilt = view != null && view.IsBuilt;
            var neural = FindFirstObjectByType<NeuralVisualizationPanel>();
            var root = view == null ? null : view.GetComponent<UIDocument>().rootVisualElement;
            report.neuralTexture = neural != null && neural.DisplayTexture != null;
            if (root != null)
            {
                var images = root.Query<Image>().ToList();
                report.gameTexture = images.Count > 0 && images[0].image != null;
                var emergency = root.Query<Button>().ToList().Find(button => button.text == "身体を停止");
                report.emergencyVisible = emergency != null && emergency.worldBound.height > 0 && root.worldBound.Contains(emergency.worldBound.center);
            }
            for (int i = 0; i < 60; i++)
            {
                var observer = neural == null ? null : neural.Observer;
                report.samples.Add(new Sample { time = Time.realtimeSinceStartup,
                    backend = observer?.Backend, mode = observer?.Mode, dataset = observer?.Dataset, state = observer?.State,
                    ready = observer != null && observer.Ready, fresh = observer != null && observer.IsFresh,
                    schematic = observer != null && observer.IsSchematic, sequence = observer?.Sequence ?? -1,
                    spikes = observer?.SpikeCount ?? 0, observed = observer?.ObservedCount ?? 0, pointCount = observer?.PointCount ?? 0,
                    ageMs = observer?.FrameAgeMs ?? -1, outputInhibited = controller == null || controller.OutputInhibited,
                    error = controller == null ? "controller unavailable" : controller.Error ?? controller.SchemaError });
                if (i == 20) ScreenCapture.CaptureScreenshot(Path.Combine(directory, "play-screen.png"));
                yield return new WaitForSecondsRealtime(.25f);
            }
            if (view != null && root != null)
            {
                // Presentation-only toggle: no settings, commands, microphone, or motor values are sent.
                view.SendMessage("ToggleSettingsDrawer", SendMessageOptions.RequireReceiver);
                yield return new WaitForSecondsRealtime(.3f);
                report.settingsOpened = view.SettingsOpen;
                ScreenCapture.CaptureScreenshot(Path.Combine(directory, "settings.png"));
                yield return new WaitForSecondsRealtime(.3f);
                view.SendMessage("ToggleSettingsDrawer", SendMessageOptions.RequireReceiver);
                report.settingsClosed = !view.SettingsOpen;
            }
            File.WriteAllText(Path.Combine(directory, "report.json"), JsonUtility.ToJson(report, true));
            Debug.Log("PLAY_SCREEN_PROBE_SAVED " + directory);
            if (FlyVisualDemo.WindowsReplayDemo.Flag("-playScreenProbeQuit")) Application.Quit();
        }
    }
}
