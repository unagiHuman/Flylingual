using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Audio;
using UnityEngine.SceneManagement;

namespace Flylingual.Audio
{
    /// <summary>Persistent scene music. Owns only its two audio sources.</summary>
    [DisallowMultipleComponent]
    public sealed class BGMManager : MonoBehaviour
    {
        [Serializable]
        public sealed class SceneBGM
        {
            public string sceneName;
            public AudioClip clip;
            [Range(0f, 1f)] public float volume = 1f;
        }

        public static BGMManager Instance { get; private set; }
        public List<SceneBGM> sceneBGMs = new List<SceneBGM>();
        public AudioMixerGroup mixerGroup;
        [Min(0f)] public float crossFadeDuration = 1.5f;
        [Range(0f, 1f)] public float masterVolume = .5f;
        public AudioClip CurrentClip { get; private set; }

        readonly AudioSource[] sources = new AudioSource[2];
        readonly float[] gains = new float[2];
        readonly float[] starts = new float[2];
        readonly float[] targets = new float[2];
        float elapsed, fadeDuration;
        bool fading;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            if (Instance != null) SceneManager.sceneLoaded -= Instance.OnSceneLoaded;
            Instance = null;
        }

        void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(this); return; }
            Instance = this;
            if (transform.parent != null) transform.SetParent(null, true);
            DontDestroyOnLoad(gameObject);
            for (int i = 0; i < sources.Length; i++)
            {
                var child = new GameObject("BGM Source " + (i + 1));
                child.transform.SetParent(transform, false);
                var source = child.AddComponent<AudioSource>();
                source.playOnAwake = false;
                source.loop = true;
                source.spatialBlend = 0f;
                source.volume = 0f;
                source.outputAudioMixerGroup = mixerGroup;
                sources[i] = source;
            }
        }

        void OnEnable()
        {
            if (Instance != this) return;
            SceneManager.sceneLoaded -= OnSceneLoaded;
            SceneManager.sceneLoaded += OnSceneLoaded;
            ApplyScene(SceneManager.GetActiveScene());
        }

        void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            // Additive scenery must not replace the active scene's music.
            if (mode == LoadSceneMode.Single || scene == SceneManager.GetActiveScene()) ApplyScene(scene);
        }

        void ApplyScene(Scene scene)
        {
            if (sceneBGMs != null)
                foreach (var mapping in sceneBGMs)
                    if (mapping != null && !string.IsNullOrEmpty(mapping.sceneName)
                        && (mapping.sceneName == scene.path || mapping.sceneName == scene.name))
                    {
                        if (mapping.clip != null) PlayBGM(mapping.clip, mapping.volume);
                        else StopBGM();
                        return;
                    }
            StopBGM();
        }

        public void PlayBGM(AudioClip clip, float volume = 1f)
        {
            if (Instance != this || !isActiveAndEnabled) return;
            if (clip == null) { StopBGM(); return; }
            int next = -1;
            for (int i = 0; i < sources.Length; i++)
                if (sources[i].clip == clip && sources[i].isPlaying) { next = i; break; }
            if (next < 0)
            {
                // With two sources, keep the louder interrupted track and reuse the quieter one.
                next = gains[0] <= gains[1] ? 0 : 1;
                sources[next].Stop();
                sources[next].clip = clip;
                gains[next] = 0f;
                sources[next].volume = 0f;
                sources[next].Play();
            }
            CurrentClip = clip;
            BeginFade(next, ClampVolume(volume), crossFadeDuration);
        }

        public void StopBGM(bool fade = true)
        {
            if (Instance != this) return;
            CurrentClip = null;
            BeginFade(-1, 0f, fade ? crossFadeDuration : 0f);
        }

        void BeginFade(int selected, float volume, float duration)
        {
            elapsed = 0f;
            fadeDuration = float.IsNaN(duration) || float.IsInfinity(duration) ? 0f : Mathf.Max(0f, duration);
            for (int i = 0; i < sources.Length; i++)
            {
                starts[i] = gains[i];
                targets[i] = i == selected ? volume : 0f;
            }
            fading = fadeDuration > 0f;
            if (!fading) CompleteFade();
        }

        void Update()
        {
            if (Instance != this) return;
            if (fading)
            {
                elapsed += Time.unscaledDeltaTime;
                float t = Mathf.Clamp01(elapsed / fadeDuration);
                for (int i = 0; i < sources.Length; i++) gains[i] = Mathf.Lerp(starts[i], targets[i], t);
                if (t >= 1f) CompleteFade();
            }
            ApplyVolumes();
        }

        void CompleteFade()
        {
            fading = false;
            for (int i = 0; i < sources.Length; i++)
            {
                gains[i] = targets[i];
                // Keep a selected zero-volume clip running so changing its volume does not restart it.
                if (sources[i] != null && sources[i].clip != CurrentClip)
                { sources[i].Stop(); sources[i].clip = null; }
            }
            ApplyVolumes();
        }

        public void SetVolume(float volume)
        {
            masterVolume = ClampVolume(volume);
            ApplyVolumes();
        }

        void ApplyVolumes()
        {
            for (int i = 0; i < sources.Length; i++)
                if (sources[i] != null) sources[i].volume = gains[i] * ClampVolume(masterVolume);
        }

        static float ClampVolume(float volume) => float.IsNaN(volume) || float.IsInfinity(volume) ? 0f : Mathf.Clamp01(volume);

        void OnDisable()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;
            if (Instance == this) StopBGM(false);
        }

        void OnDestroy()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;
            if (Instance != this) return;
            Instance = null;
            foreach (var source in sources)
                if (source != null) Destroy(source.gameObject);
        }
    }
}
