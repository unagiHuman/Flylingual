using System;
using System.Collections;
using Flylingual.Conversation;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Flylingual.PlayScreen
{
    /// <summary>Owns single-scene loads while persistent conversation services stay alive.</summary>
    public sealed class GameSceneTransition : MonoBehaviour
    {
        static GameSceneTransition instance;
        public static bool IsLoading => instance != null && instance.loading;
        bool loading;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetState() => instance = null;

        public static bool TryLoad(string scenePath, Action<string> failed = null)
        {
            if (IsLoading) return false;
            if (string.IsNullOrEmpty(scenePath) || !Application.CanStreamedLevelBeLoaded(scenePath))
            {
                failed?.Invoke(GameLanguage.Text("シーンを読み込めませんでした。ビルド設定を確認してください。", "The scene is unavailable. Check the build settings."));
                return false;
            }
            if (instance == null)
            {
                var host = new GameObject("Game Scene Transition");
                DontDestroyOnLoad(host);
                instance = host.AddComponent<GameSceneTransition>();
            }
            instance.loading = true;
            instance.StartCoroutine(instance.Load(scenePath, failed));
            return true;
        }

        IEnumerator Load(string path, Action<string> failed)
        {
            var conversation = FindFirstObjectByType<ConversationSessionController>();
            conversation?.EmergencyStop();
            if (conversation != null)
            {
                var body = conversation.GetComponent<NativeConversationBody>();
                if (body != null) { body.enabled = false; Destroy(body); }
                var reaction = conversation.GetComponent<NativeConversationReaction>();
                if (reaction != null) { reaction.enabled = false; Destroy(reaction); }
            }
            Time.timeScale = 0f;
            Debug.Log("GAME_SCENE_TRANSITION_BEGIN scene=" + path);
            // Let destroyed adapters release their scene references before loading.
            yield return null;
            AsyncOperation operation = null;
            try { operation = SceneManager.LoadSceneAsync(path, LoadSceneMode.Single); }
            catch (Exception e) { Debug.LogError("GAME_SCENE_TRANSITION_LOAD_FAILED type=" + e.GetType().Name); }
            if (operation == null)
            {
                RestoreAdapters(conversation);
                Time.timeScale = 0f;
                loading = false;
                failed?.Invoke(GameLanguage.Text("シーンの読み込みに失敗しました。もう一度お試しください。", "The scene could not be loaded. Please try again."));
                yield break;
            }
            while (!operation.isDone) yield return null;
            // Scene Start has completed before the reaction adapter caches its renderers.
            yield return null;
            RestoreAdapters(conversation);
            if (conversation == null && !NativeConversationRuntime.Enabled) Time.timeScale = 1f;
            loading = false;
            Debug.Log("GAME_SCENE_TRANSITION_LOADED scene=" + path);
        }

        static void RestoreAdapters(ConversationSessionController conversation)
        {
            if (conversation == null) return;
            if (conversation.GetComponent<NativeConversationBody>() == null)
                conversation.gameObject.AddComponent<NativeConversationBody>();
            if (conversation.GetComponent<NativeConversationReaction>() == null)
                conversation.gameObject.AddComponent<NativeConversationReaction>();
        }

        void LateUpdate()
        {
            if (loading) Time.timeScale = 0f;
        }
    }
}
