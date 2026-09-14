using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Audio;

namespace Flylingual.Audio
{
    public enum SEType { UiClick, StartGame, Retry, GameOver, Goal }

    /// <summary>Bounded sound-effect pool, independent of conversation audio.</summary>
    [DisallowMultipleComponent]
    public sealed class SEManager : MonoBehaviour
    {
        [Serializable]
        public sealed class SEEntry
        {
            public SEType type;
            public AudioClip clip;
            [Range(0f, 1f)] public float volume = 1f;
            [Range(.01f, 3f)] public float pitch = 1f;
        }

        sealed class Voice
        {
            public AudioSource source;
            public ulong order;
            public float volume;
        }

        public static SEManager Instance { get; private set; }
        public List<SEEntry> entries = new List<SEEntry>();
        public AudioMixerGroup mixerGroup;
        [Min(1)] public int poolSize = 8;
        [Min(1)] public int maxVoices = 16;
        [Range(0f, 1f)] public float masterVolume = .8f;
        readonly List<Voice> voices = new List<Voice>();
        ulong nextOrder;
        int capacity;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => Instance = null;

        void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(this); return; }
            Instance = this;
            if (transform.parent != null) transform.SetParent(null, true);
            DontDestroyOnLoad(gameObject);
            capacity = Mathf.Max(1, maxVoices);
            int initial = Mathf.Clamp(poolSize, 1, capacity);
            for (int i = 0; i < initial; i++) CreateVoice();
        }

        Voice CreateVoice()
        {
            var child = new GameObject("SE Voice " + (voices.Count + 1));
            child.transform.SetParent(transform, false);
            var source = child.AddComponent<AudioSource>();
            source.playOnAwake = false;
            source.loop = false;
            source.spatialBlend = 0f;
            source.outputAudioMixerGroup = mixerGroup;
            var voice = new Voice { source = source };
            voices.Add(voice);
            return voice;
        }

        public AudioSource Play(SEType type)
        {
            if (entries != null)
                foreach (var entry in entries)
                    if (entry != null && entry.type == type) return Play(entry.clip, entry.volume, entry.pitch);
            return null;
        }

        public AudioSource Play(AudioClip clip, float volume = 1f, float pitch = 1f)
        {
            if (Instance != this || !isActiveAndEnabled || clip == null) return null;
            Voice selected = null;
            foreach (var voice in voices)
                if (!voice.source.isPlaying) { selected = voice; break; }
            if (selected == null && voices.Count < capacity) selected = CreateVoice();
            if (selected == null)
            {
                selected = voices[0];
                foreach (var voice in voices)
                    if (voice.order < selected.order) selected = voice;
            }
            selected.source.Stop();
            selected.volume = ClampVolume(volume);
            selected.order = ++nextOrder;
            selected.source.clip = clip;
            selected.source.loop = false;
            selected.source.pitch = float.IsNaN(pitch) || float.IsInfinity(pitch) ? 1f : Mathf.Clamp(pitch, .01f, 3f);
            selected.source.volume = selected.volume * ClampVolume(masterVolume);
            selected.source.Play();
            return selected.source;
        }

        public void SetVolume(float volume)
        {
            masterVolume = ClampVolume(volume);
            foreach (var voice in voices)
                if (voice.source != null) voice.source.volume = voice.volume * masterVolume;
        }

        public void StopAll()
        {
            foreach (var voice in voices)
                if (voice.source != null) { voice.source.Stop(); voice.source.clip = null; }
        }

        static float ClampVolume(float volume) => float.IsNaN(volume) || float.IsInfinity(volume) ? 0f : Mathf.Clamp01(volume);
        void OnDisable() { if (Instance == this) StopAll(); }
        void OnDestroy()
        {
            if (Instance != this) return;
            StopAll();
            Instance = null;
            foreach (var voice in voices)
                if (voice.source != null) Destroy(voice.source.gameObject);
            voices.Clear();
        }
    }
}
