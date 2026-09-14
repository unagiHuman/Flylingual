using System;
using System.Collections;
using System.IO;
using Flylingual.BlindSugarRun;
using Flylingual.PlayScreen;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Flylingual.Conversation
{
    // Explicit real-Player verification only; never supplies motor values or Brain frames.
    public sealed class JudgeRuntimeProbe : MonoBehaviour
    {
        string output;
        [Serializable] sealed class Result
        {
            public string result = "startup_timeout", backend, error;
            public bool textSession, liveSession, brainReady, fresh, cloudFallback, stopped, cloudReplyReceived;
            public string questionTranscript;
            public long firstSequence, lastSequence;
            public float displacement;
            public string brainEndpoint = "127.0.0.1:18766";
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, "-judgeRuntimeProbe");
            if (i < 0 || i + 1 >= args.Length || FindAnyObjectByType<JudgeRuntimeProbe>() != null) return;
            var go = new GameObject("Judge runtime verification");
            DontDestroyOnLoad(go);
            go.AddComponent<JudgeRuntimeProbe>().output = Path.GetFullPath(args[i + 1]);
        }

        IEnumerator Start()
        {
            var r = new Result();
            yield return null;
            if (SceneManager.GetActiveScene().path != TitleScreen.InGameScenePath)
                yield return SceneManager.LoadSceneAsync(TitleScreen.InGameScenePath);
            ConversationSessionController c = null;
            BlindSugarRunSession stage = null;
            float deadline = Time.realtimeSinceStartup + 120;
            while (Time.realtimeSinceStartup < deadline)
            {
                c = FindAnyObjectByType<ConversationSessionController>();
                stage = FindAnyObjectByType<BlindSugarRunSession>();
                if (c != null && c.BodyControlActive && stage != null && stage.fly != null) break;
                yield return new WaitForSecondsRealtime(.2f);
            }
            if (c != null && c.BodyControlActive && stage != null && stage.fly != null)
            {
                r.textSession = c.TextConversation;
                r.liveSession = c.ConversationLive;
                r.backend = c.Backend;
                r.brainReady = c.BrainReady;
                r.firstSequence = c.Sequence;
                Vector3 initial = stage.fly.Position;
                c.SendPlayerText("前に進んで");
                yield return new WaitForSecondsRealtime(3);
                r.displacement = Vector3.Distance(initial, stage.fly.Position);
                c.SendPlayerText("止まって");
                yield return new WaitForSecondsRealtime(2);
                r.stopped = c.LastAppliedAction == "STOP";
                string beforeQuestion = c.Caption;
                c.SendPlayerText("宇宙について少し教えて");
                yield return new WaitForSecondsRealtime(6);
                r.cloudFallback = c.Caption.Contains("通信が使えない") || c.Caption.Contains("Cloud unavailable");
                r.questionTranscript = c.Caption.StartsWith(beforeQuestion) ? c.Caption.Substring(beforeQuestion.Length) : c.Caption;
                r.cloudReplyReceived = r.textSession && !r.cloudFallback && r.questionTranscript.Contains("assistant:");
                r.lastSequence = c.Sequence;
                r.fresh = c.HasFreshBrain;
                r.error = c.Error;
                r.result = c.ConversationActive && r.stopped && r.fresh && r.displacement > .05f
                    && r.lastSequence > r.firstSequence ? "control_pass" : "control_failed";
            }
            else if (c != null) r.error = c.Error;
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            File.WriteAllText(output, JsonUtility.ToJson(r, true));
            if (c != null) c.EmergencyStop();
            yield return new WaitForSecondsRealtime(1);
            Application.Quit();
        }
    }
}
