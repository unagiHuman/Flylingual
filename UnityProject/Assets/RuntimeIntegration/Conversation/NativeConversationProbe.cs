using System;
using System.Collections;
using System.IO;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Explicit development probe: real services/API, no synthetic microphone or motor.</summary>
    public sealed class NativeConversationProbe : MonoBehaviour
    {
        [Serializable] sealed class Report
        {
            public string result, bridge, backend, error;
            public bool brainReady, outputInhibited, live, stopped, microphoneTested;
            public int microphoneDevices, generation, settingsRevision;
            public long sequence, audioBytes, nonzeroAudioBytes, playedSamples, transcriptDeltas;
            public int bufferMs;
        }
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbe") < 0) return;
            new GameObject("Native conversation development probe").AddComponent<NativeConversationProbe>();
        }
        IEnumerator Start()
        {
            string path = FlyVisualDemo.WindowsReplayDemo.Argument("-flyConversationProbeOutput");
            if (string.IsNullOrEmpty(path)) { Debug.LogError("NATIVE_PROBE_OUTPUT_REQUIRED"); yield break; }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            var report = new Report { result = "startup_timeout", microphoneTested = false, bridge = "127.0.0.1" };
            ConversationSessionController controller = null;
            float deadline = Time.realtimeSinceStartup + 65;
            while (Time.realtimeSinceStartup < deadline)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                if (controller != null && controller.Ready) break;
                yield return new WaitForSecondsRealtime(.1f);
            }
            if (controller != null && controller.Ready)
            {
                ScreenCapture.CaptureScreenshot(Path.ChangeExtension(path, ".png"));
                report.microphoneDevices = controller.Devices.Length;
                int revision = controller.SettingsRevision;
                var settings = controller.Settings;
                controller.ApplySettings(settings.language, settings.voice, settings.persona, settings.personaText);
                deadline = Time.realtimeSinceStartup + 5;
                while (Time.realtimeSinceStartup < deadline && controller.SettingsRevision == revision)
                    yield return new WaitForSecondsRealtime(.1f);
                controller.StartConversation();
                deadline = Time.realtimeSinceStartup + 45;
                while (Time.realtimeSinceStartup < deadline)
                {
                    if (controller.ConversationLive && controller.ReceivedNonzeroAudioBytes > 0
                        && controller.ReceivedTranscriptDeltas > 0 && controller.PlayedSamples > 0) break;
                    yield return new WaitForSecondsRealtime(.1f);
                }
                report.backend = controller.Backend;
                report.brainReady = controller.BrainReady;
                report.outputInhibited = controller.OutputInhibited;
                report.live = controller.ConversationLive;
                report.sequence = controller.Sequence;
                report.generation = controller.ConversationGeneration;
                report.settingsRevision = controller.SettingsRevision;
                report.audioBytes = controller.ReceivedAudioBytes;
                report.nonzeroAudioBytes = controller.ReceivedNonzeroAudioBytes;
                report.transcriptDeltas = controller.ReceivedTranscriptDeltas;
                report.playedSamples = controller.PlayedSamples;
                report.error = controller.Error;
                controller.StopConversation();
                yield return new WaitForSecondsRealtime(3);
                report.stopped = !controller.ConversationLive;
                report.bufferMs = controller.BufferedMilliseconds;
                report.result = report.live && report.nonzeroAudioBytes > 0 && report.transcriptDeltas > 0
                    && report.playedSamples > 0 && report.outputInhibited && report.stopped && report.bufferMs == 0
                    && report.sequence > 0 && report.settingsRevision > revision ? "transport_audio_pass" : "incomplete";
            }
            File.WriteAllText(path, JsonUtility.ToJson(report, true));
            Debug.Log("NATIVE_PROBE_RESULT " + report.result);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversationProbeQuit") >= 0) Application.Quit();
        }
    }
}
