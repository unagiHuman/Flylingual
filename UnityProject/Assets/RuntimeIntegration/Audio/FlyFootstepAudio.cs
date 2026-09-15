using Flylingual.BlindSugarRun;
using Flylingual.Conversation;
using Flylingual.PlayScreen;
using FlyLocomotionPoC;
using UnityEngine;
using UnityEngine.Audio;

namespace Flylingual.Audio
{
    /// <summary>Plays a small local footfall only after actual grounded FlyBody displacement.</summary>
    [DisallowMultipleComponent]
    public sealed class FlyFootstepAudio : MonoBehaviour
    {
        [Range(.03f, .5f)] public float strideMeters = .12f;
        [Range(.005f, .08f)] public float minimumMovementMeters = .015f;
        [Range(.01f, .5f)] public float volume = .14f;
        [Range(1f, 20f)] public float maximumStepsPerSecond = 10f;
        public int PlayedSteps { get; private set; }

        BlindSugarRunSession stage;
        ConversationSessionController controller;
        FlyBody body;
        GameObject audioObject;
        AudioSource source;
        AudioClip[] clips;
        Vector3 motionAnchor;
        float accumulatedDistance;
        float nextStepAt;
        bool hasAnchor;

        void Awake()
        {
            CreateAudio();
        }

        void OnEnable()
        {
            ResetMotion();
        }

        void Update()
        {
            BindReferences();
            if (!CanPlaySteps())
            {
                StopAndReset();
                return;
            }

            Vector3 currentPosition = body.Position;
            if (!hasAnchor)
            {
                motionAnchor = currentPosition;
                hasAnchor = true;
                return;
            }

            Vector3 delta = currentPosition - motionAnchor;
            delta.y = 0f;
            float movement = delta.magnitude;
            if (movement > 1f)
            {
                ResetMotion();
                motionAnchor = currentPosition;
                hasAnchor = true;
                return;
            }

            // Retain the anchor until real travel exceeds the noise floor, so resting Physics jitter does not accumulate.
            if (movement < minimumMovementMeters) return;
            motionAnchor = currentPosition;
            accumulatedDistance += movement;

            float stride = Mathf.Max(.03f, strideMeters);
            if (accumulatedDistance < stride || Time.unscaledTime < nextStepAt) return;
            accumulatedDistance -= stride;
            PlayStep();
            nextStepAt = Time.unscaledTime + 1f / Mathf.Max(1f, maximumStepsPerSecond);
        }

        void BindReferences()
        {
            if (stage == null) stage = FindFirstObjectByType<BlindSugarRunSession>();
            if (controller == null) controller = FindFirstObjectByType<ConversationSessionController>();
            if (stage != null && stage.fly != null) body = stage.fly;
            else if (body == null) body = FindFirstObjectByType<FlyBody>();
        }

        bool CanPlaySteps()
        {
            return stage != null && stage.State == BlindSugarRunSession.StageState.Playing && body != null
                && body.GroundContactCount > 0 && !TitleScreen.BlocksGameplay && Time.timeScale > 0f
                && controller != null && controller.HasFreshBrain && controller.BodyControlActive;
        }

        void CreateAudio()
        {
            audioObject = new GameObject("Fly Footstep Audio");
            audioObject.transform.SetParent(transform, false);
            source = audioObject.AddComponent<AudioSource>();
            source.playOnAwake = false;
            source.loop = false;
            source.spatialBlend = 0f;
            source.dopplerLevel = 0f;

            AudioReverbFilter reverb = audioObject.AddComponent<AudioReverbFilter>();
            reverb.reverbPreset = AudioReverbPreset.User;
            reverb.room = -1000;
            reverb.roomHF = -600;
            reverb.roomRolloffFactor = 0f;
            reverb.decayTime = .65f;
            reverb.decayHFRatio = .7f;
            reverb.reflectionsLevel = -1200;
            reverb.reflectionsDelay = 0f;
            reverb.reverbLevel = -800;
            reverb.reverbDelay = .025f;
            reverb.hfReference = 5000f;
            reverb.lfReference = 250f;
            reverb.diffusion = 100f;
            reverb.density = 100f;
            reverb.dryLevel = 0;

            clips = new[] { CreateTick("Fly Footstep Tick 1", 0x9E3779B9u), CreateTick("Fly Footstep Tick 2", 0x3C6EF372u), CreateTick("Fly Footstep Tick 3", 0xDAA66D2Bu) };
        }

        void PlayStep()
        {
            if (source == null || clips == null || clips.Length == 0) return;
            int index = PlayedSteps % clips.Length;
            SEManager manager = SEManager.Instance;
            source.outputAudioMixerGroup = manager == null ? null : manager.mixerGroup;
            float master = manager == null ? 1f : Mathf.Clamp01(manager.masterVolume);
            float duck = controller != null && controller.ReplyPlaying ? .45f : 1f;
            source.volume = Mathf.Clamp01(volume) * master * duck;
            source.pitch = index == 0 ? .96f : index == 1 ? 1.02f : 1.07f;
            source.panStereo = (PlayedSteps & 1) == 0 ? -.12f : .12f;
            source.clip = clips[index];
            source.Play();
            PlayedSteps++;
        }

        static AudioClip CreateTick(string clipName, uint seed)
        {
            const int sampleRate = 48000;
            const int sampleCount = 2304;
            var samples = new float[sampleCount];
            uint state = seed;
            for (int i = 0; i < sampleCount; i++)
            {
                float t = i / (float)sampleRate;
                float envelope = Mathf.Exp(-t * 85f) * Mathf.Clamp01(t * 1800f);
                float noise = NextNoise(ref state);
                float knock = Mathf.Sin(t * (760f + (seed & 255u) * 2f) * Mathf.PI * 2f);
                samples[i] = (noise * .38f + knock * .18f) * envelope * .52f;
            }
            var clip = AudioClip.Create(clipName, sampleCount, 1, sampleRate, false);
            clip.SetData(samples, 0);
            return clip;
        }

        static float NextNoise(ref uint state)
        {
            state = state * 1664525u + 1013904223u;
            return ((state >> 8) & 0x00FFFFFF) / 8388607.5f - 1f;
        }

        void StopAndReset()
        {
            if (source != null && source.isPlaying) source.Stop();
            ResetMotion();
        }

        void ResetMotion()
        {
            hasAnchor = false;
            accumulatedDistance = 0f;
            nextStepAt = 0f;
        }

        void OnDisable()
        {
            StopAndReset();
        }

        void OnDestroy()
        {
            if (source != null) source.Stop();
            if (clips != null)
                for (int i = 0; i < clips.Length; i++)
                    if (clips[i] != null) Destroy(clips[i]);
            if (audioObject != null) Destroy(audioObject);
        }
    }
}

