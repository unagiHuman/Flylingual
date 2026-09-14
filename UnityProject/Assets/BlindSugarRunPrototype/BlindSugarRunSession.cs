using System.Collections;
using Flylingual.Conversation;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEngine;
using Flylingual.PlayScreen;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Stage failure/retry only. Locomotion remains on the existing native Brain route.</summary>
    [DefaultExecutionOrder(-1500)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunSession : MonoBehaviour
    {
        public enum StageState { Playing, GameOver, Interrupted, Retrying, Goal, Reveal }
        public FlyBody fly;
        public BoxCollider killVolume;
        public float fallHeight = -2f;

        static string pendingScene;
        static int nextAttempt = 1;
        static bool? pendingRetryMicrophoneMute;
        bool microphoneMutedBeforeGoal;
        ConversationSessionController conversation;
        NativeConversationBody nativeBody;
        BlindSugarRunGameOverView view;
        public StageState State { get; private set; }
        public int Attempt { get; private set; } = 1;
        public int Deaths { get; private set; }
        public bool OverlayVisible => view != null && view.Visible;
        public Vector3 LastFallPosition { get; private set; }
        public string LastFallAction { get; private set; }
        static int deaths;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetSession() { pendingScene = null; nextAttempt = 1; deaths = 0; pendingRetryMicrophoneMute = null; }

        IEnumerator Start()
        {
            if (GetComponent<BlindSugarRunNarrator>() == null) gameObject.AddComponent<BlindSugarRunNarrator>();
            if (GetComponent<BlindSugarRunGoal>() == null) gameObject.AddComponent<BlindSugarRunGoal>();
            if (GetComponent<FlyDemoSafetyAssist>() == null) gameObject.AddComponent<FlyDemoSafetyAssist>();
            if (GetComponent<BlindSugarRunIdleSwatter>() == null) gameObject.AddComponent<BlindSugarRunIdleSwatter>();
            view = gameObject.AddComponent<BlindSugarRunGameOverView>();
            if (fly == null) { Debug.LogError("BLIND_SUGAR_SESSION_MISSING_FLY"); enabled = false; yield break; }
            bool restoring = pendingScene == gameObject.scene.path;
            Attempt = restoring ? nextAttempt : 1;
            if (GetComponent<BlindSugarRunEnvironmentFeedback>() == null) gameObject.AddComponent<BlindSugarRunEnvironmentFeedback>();
            Deaths = deaths;
            State = restoring ? StageState.Retrying : StageState.Playing;
            if (!restoring) yield break;
            pendingScene = null;
            view.ShowBusy(GameLanguage.Text("開始地点と音声操作を準備しています…", "Preparing the starting point and voice controls…"), Attempt);
            // Scene Awake/Start must finish before recreating adapters that cache the scene's Fly.
            yield return null;
            yield return ResumeAtStart();
        }

        void BindConversation()
        {
            if (conversation == null) conversation = FindFirstObjectByType<ConversationSessionController>();
            if (conversation != null && nativeBody == null) nativeBody = conversation.GetComponent<NativeConversationBody>();
        }

        void Update()
        {
            BindConversation();
            if (State == StageState.GameOver || State == StageState.Interrupted)
            {
                // A button, pending voice-start routine, or late state event cannot unlatch game over.
                if (conversation != null && (conversation.IsSessionRequested || conversation.ContinuousVoiceControl ||
                    conversation.EnablingVoiceActions || conversation.BodyControlActive)) conversation.EmergencyStop();
                if (nativeBody != null && nativeBody.enabled) nativeBody.enabled = false;
                return;
            }
            if (State != StageState.Playing || fly == null || view == null) return;
            Vector3 position = fly.Position;
            if (position.y >= fallHeight && (killVolume == null || !killVolume.bounds.Contains(position))) return;
            bool healthy = conversation != null && conversation.HasFreshBrain && conversation.BodyControlActive &&
                nativeBody != null && nativeBody.BodyActive && string.IsNullOrEmpty(nativeBody.Fault);
            LastFallPosition = position;
            LastFallAction = conversation == null ? "unknown" : conversation.LastAppliedAction ?? "unknown";
            GetComponent<BlindSugarRunNarrator>()?.NotifyFall(healthy, LastFallAction);
            GetComponent<BlindSugarRunEnvironmentFeedback>()?.Finish(healthy);
            StopAttempt();
            if (healthy)
            {
                State = StageState.GameOver;
                Flylingual.Audio.SEManager.Instance?.Play(Flylingual.Audio.SEType.GameOver);
                Deaths = ++deaths;
                view.Show("GAME OVER", GameLanguage.Text("崖から落下しました。\n開始地点からもう一度挑戦できます。", "You fell off the edge.\nTry again from the starting point."), Attempt, () => BeginRetry());
            }
            else
            {
                // A known transport/Brain fault is an interruption, never an ordinary death.
                State = StageState.Interrupted;
                view.Show(GameLanguage.Text("プレイを中断しました", "Play interrupted"), GameLanguage.Text("落下時の接続状態を確認できませんでした。\n接続を確認して、開始地点からやり直してください。", "The connection could not be verified when you fell.\nCheck the connection and try again."), Attempt, () => BeginRetry());
            }
            Debug.Log("BLIND_SUGAR_FALL state=" + State + " attempt=" + Attempt + " deaths=" + Deaths +
                " position=" + position + " lastObservedAction=" + LastFallAction);
        }

        void StopAttempt()
        {
            BindConversation();
            conversation?.EmergencyStop();
            // OnDisable uses NativeConversationBody.Deactivate: source detach, TCP close, timeScale=0.
            if (nativeBody != null) nativeBody.enabled = false;
            Time.timeScale = 0f;
        }

        internal void KillBySwatter()
        {
            if (State != StageState.Playing || fly == null || view == null) return;
            LastFallPosition = fly.Position;
            LastFallAction = conversation == null ? "unknown" : conversation.LastAppliedAction ?? "unknown";
            GetComponent<BlindSugarRunNarrator>()?.NotifySwatted();
            GetComponent<BlindSugarRunEnvironmentFeedback>()?.Finish(false, true);
            State = StageState.GameOver;
            Flylingual.Audio.SEManager.Instance?.Play(Flylingual.Audio.SEType.GameOver);
            Deaths = ++deaths;
            StopAttempt();
            view.Show("GAME OVER", GameLanguage.Text("動かずにいたため、ハエたたきに叩かれました。\n開始地点からもう一度挑戦できます。", "You stayed still and were hit by the fly swatter.\nTry again from the starting point."), Attempt, () => BeginRetry());
            Debug.Log("BLIND_SUGAR_SWATTED attempt=" + Attempt + " deaths=" + Deaths + " position=" + LastFallPosition);
        }

        internal void ConfirmGoal()
        {
            if (State != StageState.Playing) return;
            State = StageState.Goal;
            GetComponent<BlindSugarRunEnvironmentFeedback>()?.Finish(false);
            Flylingual.Audio.SEManager.Instance?.Play(Flylingual.Audio.SEType.Goal);
            BindConversation();
            // Completion pauses PhysX; keep the existing live adapters running for final speech.
            Time.timeScale = 0f;
            microphoneMutedBeforeGoal = conversation != null && conversation.MicrophoneMuted;
            conversation?.SetMicrophoneMuted(true);
            var narrator = GetComponent<BlindSugarRunNarrator>();
            narrator?.NotifyGoalConfirmed(true, true, true);
            gameObject.AddComponent<BlindSugarRunReveal>().Begin(fly, narrator, conversation);
            Debug.Log("BLIND_SUGAR_GOAL_CONFIRMED attempt=" + Attempt + " stableSeconds=1 epoch=" + conversation?.ControlEpoch);
        }

        public void MarkRevealStarted()
        {
            if (State == StageState.Goal) State = StageState.Reveal;
        }

        void LateUpdate()
        {
            if (State != StageState.Goal && State != StageState.Reveal) return;
            Time.timeScale = 0f;
            conversation?.SetMicrophoneMuted(true);
        }

        public bool BeginRetry()
        {
            if (GameSceneTransition.IsLoading) return false;
            bool completedReveal = (State == StageState.Goal || State == StageState.Reveal)
                && GetComponent<BlindSugarRunReveal>() != null && GetComponent<BlindSugarRunReveal>().Complete;
            if (State != StageState.GameOver && State != StageState.Interrupted && !completedReveal) return false;
            Flylingual.Audio.SEManager.Instance?.Play(Flylingual.Audio.SEType.Retry);
            if (completedReveal) pendingRetryMicrophoneMute = microphoneMutedBeforeGoal;
            State = StageState.Retrying;
            view.ShowBusy(GameLanguage.Text("開始地点へ戻っています…", "Returning to the starting point…"), Attempt + 1);
            StopAttempt();
            pendingScene = gameObject.scene.path;
            nextAttempt = Attempt + 1;
            return GameSceneTransition.TryLoad(pendingScene, message =>
            {
                pendingScene = null;
                RetryFailed(message);
            });
        }

        IEnumerator ResumeAtStart()
        {
            while (GameSceneTransition.IsLoading) yield return null;
            Time.timeScale = 0f;
            float deadline = Time.realtimeSinceStartup + 15f;
            while (conversation == null && Time.realtimeSinceStartup < deadline) { BindConversation(); yield return null; }
            if (conversation == null) { RetryFailed(GameLanguage.Text("接続の準備ができませんでした。", "The connection was not ready.")); yield break; }
            var demo = FindFirstObjectByType<WindowsReplayDemo>();
            if (demo == null || demo.body != fly) { RetryFailed(GameLanguage.Text("ハエの再配置を確認できませんでした。", "The fly could not be located at the starting point.")); yield break; }
            if (conversation.GetComponent<NativeConversationBody>() == null)
                nativeBody = conversation.gameObject.AddComponent<NativeConversationBody>();
            else nativeBody = conversation.GetComponent<NativeConversationBody>();
            nativeBody.enabled = true;
            if (conversation.GetComponent<NativeConversationReaction>() == null)
                conversation.gameObject.AddComponent<NativeConversationReaction>();

            while (Time.realtimeSinceStartup < deadline &&
                (!conversation.Ready || !conversation.HasFreshBrain || !conversation.VoiceActionsAvailable || !conversation.OutputInhibited)) yield return null;
            if (!conversation.Ready || !conversation.HasFreshBrain || !conversation.VoiceActionsAvailable || !conversation.OutputInhibited)
            { RetryFailed(GameLanguage.Text("接続の停止確認ができませんでした。", "The stopped connection could not be confirmed.")); yield break; }
            // The explicit retry click authorizes a fresh STOP/voice-generation/resume handshake.
            // No old Action, microphone buffer, or motor value is submitted again.
            if (pendingRetryMicrophoneMute.HasValue)
            {
                conversation.SetMicrophoneMuted(pendingRetryMicrophoneMute.Value);
                pendingRetryMicrophoneMute = null;
            }
            conversation.EnableVoiceActions();
            deadline = Time.realtimeSinceStartup + 65f;
            while (Time.realtimeSinceStartup < deadline && !(conversation.BodyControlActive && nativeBody.BodyActive)) yield return null;
            if (!conversation.BodyControlActive || !nativeBody.BodyActive)
            { RetryFailed(GameLanguage.Text("音声操作を再開できませんでした。", "Voice controls could not be resumed.")); yield break; }
            State = StageState.Playing;
            view.Hide();
            Debug.Log("BLIND_SUGAR_RETRY_READY attempt=" + Attempt + " position=" + fly.Position +
                " epoch=" + conversation.ControlEpoch + " sequence=" + nativeBody.TcpSequence);
        }

        void RetryFailed(string message)
        {
            StopAttempt();
            State = StageState.Interrupted;
            view.Show(GameLanguage.Text("再開の準備ができませんでした", "Unable to resume"), message + GameLanguage.Text("\n接続を確認して、もう一度リトライしてください。", "\nCheck the connection and try again."), Attempt, () => BeginRetry());
        }
    }
}
