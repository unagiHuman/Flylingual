#if UNITY_EDITOR || DEVELOPMENT_BUILD
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Flylingual.Conversation;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Opt-in real Brain/PhysX regression probe. Removes a floor; never drives the fly.</summary>
    public sealed class BlindSugarRunRetryProbe : MonoBehaviour
    {
        static bool installed;
        string outputDirectory;
        readonly Report report = new Report();

        [Serializable] public sealed class Report
        {
            public string status = "RUNNING", error, scene;
            public bool movementCommandTested;
            public string endpoint = "127.0.0.1:18766";
            public string method = "Existing player_text / real Brain / PhysX. Disable StartArea collider to induce fall. Retry via UI submit. No replay, mock, fixed motors or body teleport.";
            public List<Sample> samples = new List<Sample>();
        }
        [Serializable] public sealed class Sample
        {
            public string phase, state, backend, sessionId, instanceId, fault, lastAction;
            public string controllerId, bodyId, flyId; public int attempt, deaths, epoch, generation, appliedActions, tcpSequence;
            public long sequence;
            public float elapsed, frameAgeMs, timeScale;
            public Vector3 position;
            public bool brainReady, fresh, controlActive, bodyActive, bodyEnabled, overlayVisible, retryEnabled, continuousVoice;
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() { installed = false; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (installed) return;
            var args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, "-blindSugarRetryProbe");
            if (index < 0 || index + 1 >= args.Length) return;
            installed = true;
            var go = new GameObject("Blind Sugar Run Retry Probe");
            DontDestroyOnLoad(go);
            go.AddComponent<BlindSugarRunRetryProbe>().outputDirectory = Path.GetFullPath(args[index + 1]);
        }

        IEnumerator Start()
        {
            Directory.CreateDirectory(outputDirectory);
            report.scene = SceneManager.GetActiveScene().path;
            // Drive nested enumerators explicitly so assertions in any coroutine reach the report.
            var stack = new Stack<IEnumerator>();
            stack.Push(Run());
            float deadline = Time.realtimeSinceStartup + 300f;
            while (stack.Count > 0)
            {
                object yielded = null;
                bool moved = false;
                try
                {
                    Require(Time.realtimeSinceStartup < deadline, "Overall probe deadline");
                    moved = stack.Peek().MoveNext();
                    if (moved) yielded = stack.Peek().Current;
                }
                catch (Exception e) { report.error = e.ToString(); break; }
                if (!moved) { stack.Pop(); continue; }
                if (yielded is IEnumerator nested) { stack.Push(nested); continue; }
                yield return yielded;
            }
            report.status = report.error == null ? "PASS" : "FAIL";
            Capture("final");
            Debug.Log("BLIND_SUGAR_RETRY_PROBE_" + report.status + " " + report.error);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-blindSugarRetryProbeQuit") >= 0)
                Application.Quit(report.status == "PASS" ? 0 : 1);
        }

        IEnumerator Run()
        {
            yield return WaitFor(() => Healthy(1), 90f, "Initial Windows Brain/body did not become healthy");
            var controller = FindAnyObjectByType<ConversationSessionController>();
            Capture("initial_ready");
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-blindSugarRetryProbeSkipMovement") < 0)
            {
                int before = controller.AppliedActions;
                controller.SendPlayerText("止めるまで前に進み続けて");
                yield return WaitFor(() => controller.AppliedActions > before && controller.LastAppliedAction == "FORWARD", 30f, "Real FORWARD not applied");
                report.movementCommandTested = true;
                Capture("persistent_forward_applied");
            }
            for (int attempt = 1; attempt <= 2; attempt++)
            {
                var session = FindAnyObjectByType<BlindSugarRunSession>();
                var oldBody = controller.GetComponent<NativeConversationBody>();
                string oldBodyId = oldBody.GetEntityId().ToString(), oldFlyId = session.fly.GetEntityId().ToString();
                string controllerId = controller.GetEntityId().ToString(); int oldEpoch = controller.ControlEpoch;
                int oldGeneration = controller.ConversationGeneration;
                Transform floor = GameObject.Find("BlindSugarRunEnvironment")?.transform.Find("EnvironmentGeometry/StartArea");
                var collider = floor == null ? null : floor.GetComponent<Collider>();
                Require(collider != null, "StartArea collider missing");
                collider.enabled = false;
                Physics.SyncTransforms();
                yield return WaitFor(() => session.State != BlindSugarRunSession.StageState.Playing, 12f, "PhysX fall not observed");
                Capture("game_over_" + attempt);
                Require(session.State == BlindSugarRunSession.StageState.GameOver, "Fall classified as interruption");
                var view = session.GetComponent<BlindSugarRunGameOverView>();
                Require(session.fly.Position.y < session.fallHeight && session.Deaths == attempt, "Fall/death count invalid");
                Require(!oldBody.enabled && !oldBody.BodyActive && !controller.BodyControlActive &&
                    !controller.ContinuousVoiceControl && session.OverlayVisible && view.RetryButton.enabledInHierarchy &&
                    Time.timeScale == 0f, "Game over did not stop and show retry");
                Vector3 frozen = session.fly.Position;
                yield return new WaitForSecondsRealtime(1f);
                Require(session.State == BlindSugarRunSession.StageState.GameOver &&
                    Vector3.Distance(frozen, session.fly.Position) < .001f && !oldBody.enabled, "Game over did not remain latched");
                if (attempt == 1) yield return CaptureOverlay(view);
                using (var submit = NavigationSubmitEvent.GetPooled()) view.RetryButton.SendEvent(submit);
                Require(session.State == BlindSugarRunSession.StageState.Retrying, "UI retry submit did not start retry");
                Require(!session.BeginRetry(), "Duplicate retry accepted");
                yield return WaitFor(() => Healthy(attempt + 1), 90f, "Retry did not reach healthy Playing state");
                session = FindAnyObjectByType<BlindSugarRunSession>();
                var newBody = controller.GetComponent<NativeConversationBody>();
                Transform start = GameObject.Find("BlindSugarRunEnvironment")?.transform.Find("Anchors/Start");
                Require(controller.GetEntityId().ToString() == controllerId && newBody.GetEntityId().ToString() != oldBodyId &&
                    session.fly.GetEntityId().ToString() != oldFlyId, "Persistent controller / fresh scene adapter invariant failed");
                Require(start != null && Vector3.Distance(session.fly.Position, start.position) < 2f, "Retry did not restore Start position");
                Require(!session.OverlayVisible && controller.ControlEpoch > oldEpoch &&
                    controller.ConversationGeneration > oldGeneration, "Retry did not establish a fresh control boundary");
                Capture("retry_ready_" + session.Attempt);
                int appliedAtRetry = controller.AppliedActions, tcpAtRetry = newBody.TcpSequence;
                yield return new WaitForSecondsRealtime(2f);
                Require(newBody.TcpSequence > tcpAtRetry && controller.HasFreshBrain && newBody.BodyActive, "Retry frames did not progress");
                Require(controller.AppliedActions == appliedAtRetry, "Old player command was reapplied after retry");
                Require(FindObjectsByType<NativeConversationBody>().Length == 1 &&
                    FindObjectsByType<NativeConversationReaction>().Length == 1 &&
                    FindObjectsByType<ConversationSessionController>().Length == 1, "Duplicate persistent adapters");
                Capture("retry_stable_" + session.Attempt);
            }
        }

        IEnumerator CaptureOverlay(BlindSugarRunGameOverView view)
        {
            // Render the actual runtime panel to a texture, including when the test window is hidden.
            var settings = view.GetComponent<UIDocument>().panelSettings;
            var previous = settings.targetTexture;
            var target = new RenderTexture(1280, 720, 24);
            target.Create();
            settings.targetTexture = target;
            yield return null;
            yield return null;
            yield return null;
            var active = RenderTexture.active;
            RenderTexture.active = target;
            var texture = new Texture2D(1280, 720, TextureFormat.RGBA32, false);
            texture.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0);
            texture.Apply();
            File.WriteAllBytes(Path.Combine(outputDirectory, "game-over.png"), texture.EncodeToPNG());
            RenderTexture.active = active;
            settings.targetTexture = previous;
            Destroy(texture);
            target.Release();
            Destroy(target);
            yield return null;
        }

        bool Healthy(int attempt)
        {
            var s = FindAnyObjectByType<BlindSugarRunSession>();
            var c = FindAnyObjectByType<ConversationSessionController>();
            var b = c == null ? null : c.GetComponent<NativeConversationBody>();
            return s != null && s.Attempt == attempt && s.State == BlindSugarRunSession.StageState.Playing &&
                c != null && c.HasFreshBrain && c.BodyControlActive && b != null && b.BodyActive;
        }

        void Capture(string phase)
        {
            var s = FindAnyObjectByType<BlindSugarRunSession>();
            var c = FindAnyObjectByType<ConversationSessionController>();
            var b = c == null ? null : c.GetComponent<NativeConversationBody>();
            report.samples.Add(new Sample {
                phase = phase, state = s == null ? "missing" : s.State.ToString(), attempt = s == null ? -1 : s.Attempt,
                deaths = s == null ? -1 : s.Deaths, position = s?.fly == null ? Vector3.zero : s.fly.Position,
                controllerId = c == null ? null : c.GetEntityId().ToString(), bodyId = b == null ? null : b.GetEntityId().ToString(),
                flyId = s?.fly == null ? null : s.fly.GetEntityId().ToString(), backend = c?.Backend, sessionId = c?.BrainSessionId,
                instanceId = c?.BrainInstanceId, epoch = c == null ? -1 : c.ControlEpoch,
                generation = c == null ? -1 : c.ConversationGeneration, sequence = c == null ? -1 : c.Sequence,
                tcpSequence = b == null ? -1 : b.TcpSequence, appliedActions = c == null ? -1 : c.AppliedActions,
                lastAction = c?.LastAppliedAction, frameAgeMs = c == null ? -1 : c.FrameAgeMs,
                fault = b?.Fault, brainReady = c != null && c.BrainReady, fresh = c != null && c.HasFreshBrain,
                controlActive = c != null && c.BodyControlActive, bodyActive = b != null && b.BodyActive,
                bodyEnabled = b != null && b.enabled, overlayVisible = s != null && s.OverlayVisible,
                retryEnabled = s != null && (s.GetComponent<BlindSugarRunGameOverView>()?.RetryButton?.enabledInHierarchy ?? false),
                continuousVoice = c != null && c.ContinuousVoiceControl, timeScale = Time.timeScale, elapsed = Time.realtimeSinceStartup
            });
            File.WriteAllText(Path.Combine(outputDirectory, "retry-probe.json"), JsonUtility.ToJson(report, true));
        }

        IEnumerator WaitFor(Func<bool> predicate, float seconds, string error)
        {
            float deadline = Time.realtimeSinceStartup + seconds;
            while (Time.realtimeSinceStartup < deadline) { if (predicate()) yield break; yield return null; }
            throw new TimeoutException(error);
        }

        static void Require(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
    }
}
#endif
