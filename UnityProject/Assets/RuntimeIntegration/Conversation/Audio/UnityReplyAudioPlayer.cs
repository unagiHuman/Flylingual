using System;
using System.Threading;
using UnityEngine;

namespace Flylingual.Conversation
{
    [RequireComponent(typeof(AudioSource))]
    public sealed class UnityReplyAudioPlayer : MonoBehaviour
    {
        const int InputRate = PcmStreamConverter.TargetSampleRate;
        const int MaximumBufferedMilliseconds = 10000;
        const string OddPcm = "reply_pcm_odd_length";
        const string BufferOverflow = "reply_audio_buffer_overflow";
        readonly object gate = new object();
        readonly float[] queue = new float[InputRate * MaximumBufferedMilliseconds / 1000];
        readonly bool[] nonZero = new bool[InputRate * MaximumBufferedMilliseconds / 1000];
        AudioSource source;
        AudioClip silenceClip;
        int readIndex, writeIndex, queued, nonZeroQueued;
        volatile int outputSampleRate;
        double phase;
        float volume = 1f;
        volatile bool playing;
        long playedSamples;
        long playedNonzeroSamples;
        long underruns;

        public bool IsPlaying => playing;
        public int BufferedMilliseconds { get { lock (gate) return queued * 1000 / InputRate; } }
        // Applied in the audio callback so the value is not multiplied again by AudioSource.volume.
        public float Volume { get => volume; set => volume = Math.Max(0f, Math.Min(1f, value)); }
        public int OutputSampleRate => outputSampleRate;
        public long PlayedSamples => Interlocked.Read(ref playedSamples);
        // Counts non-zero mono frames after the configured reply volume has been applied.
        public long PlayedNonzeroSamples => Interlocked.Read(ref playedNonzeroSamples);
        public long Underruns => Interlocked.Read(ref underruns);
        public string Error { get; private set; }

        void Awake()
        {
            source = GetComponent<AudioSource>();
            source.playOnAwake = false;
            source.loop = true;
            source.spatialBlend = 0f;
            RefreshOutputSampleRate();
        }

        void OnEnable()
        {
            AudioSettings.OnAudioConfigurationChanged += OnAudioConfigurationChanged;
            RebuildSilenceClip();
        }

        void OnAudioConfigurationChanged(bool deviceWasChanged)
        {
            RefreshOutputSampleRate();
            RebuildSilenceClip();
        }

        void RefreshOutputSampleRate() => outputSampleRate = Math.Max(1, AudioSettings.outputSampleRate);

        void RebuildSilenceClip()
        {
            if (source == null) return;
            source.Stop();
            if (silenceClip != null) Destroy(silenceClip);
            silenceClip = AudioClip.Create("FlylingualReplySilence", outputSampleRate, 1, outputSampleRate, false);
            source.clip = silenceClip;
            source.Play();
        }

        public void EnqueuePcm(byte[] pcm)
        {
            if (pcm == null || pcm.Length == 0) return;
            if ((pcm.Length & 1) != 0) { Error = OddPcm; return; }
            lock (gate)
            {
                for (int i = 0; i < pcm.Length; i += 2)
                {
                    short value = (short)(pcm[i] | (pcm[i + 1] << 8));
                    if (queued == queue.Length)
                    {
                        if (nonZero[readIndex]) nonZeroQueued--;
                        readIndex = (readIndex + 1) % queue.Length;
                        queued--;
                        Error = BufferOverflow;
                    }
                    queue[writeIndex] = value / 32768f;
                    nonZero[writeIndex] = value != 0;
                    if (nonZero[writeIndex]) nonZeroQueued++;
                    writeIndex = (writeIndex + 1) % queue.Length;
                    queued++;
                }
                playing = nonZeroQueued > 0;
            }
        }

        public void Discard()
        {
            lock (gate)
            {
                readIndex = writeIndex = queued = nonZeroQueued = 0;
                phase = 0d;
                playing = false;
            }
        }

        void OnAudioFilterRead(float[] data, int channels)
        {
            Array.Clear(data, 0, data.Length);
            int outputRate = outputSampleRate;
            if (channels <= 0 || outputRate <= 0) return;
            int frames = data.Length / channels;
            bool hadUnderrun = false;
            bool playedNonZero = false;
            int playedFrames = 0;
            int playedNonzeroFrames = 0;
            lock (gate)
            {
                for (int frame = 0; frame < frames; frame++)
                {
                    if (queued == 0) continue;
                    float a = queue[readIndex];
                    float b = queued > 1 ? queue[(readIndex + 1) % queue.Length] : a;
                    float interpolated = (float)(a + (b - a) * phase);
                    float sample = interpolated * volume;
                    playedNonZero |= interpolated != 0f;
                    if (sample != 0f) playedNonzeroFrames++;
                    int baseIndex = frame * channels;
                    for (int channel = 0; channel < channels; channel++) data[baseIndex + channel] = sample;
                    int consume;
                    if (queued == 1)
                    {
                        phase += (double)InputRate / outputRate;
                        consume = phase >= 1d ? 1 : 0;
                        if (consume == 1) { phase = 0d; hadUnderrun = true; }
                    }
                    else consume = PcmResamplingStep.Consume(ref phase, queued, InputRate, outputRate);
                    if (consume > 0)
                    {
                        for (int consumed = 0; consumed < consume; consumed++)
                        {
                            if (nonZero[readIndex]) nonZeroQueued--;
                            readIndex = (readIndex + 1) % queue.Length;
                        }
                        queued -= consume;
                    }
                    playedFrames++;
                }
                // Keep the state through the callback that emitted the final non-zero
                // sample; the controller can then apply its 200 ms tail inhibition.
                playing = nonZeroQueued > 0 || playedNonZero;
            }
            if (playedFrames > 0) Interlocked.Add(ref playedSamples, playedFrames);
            if (playedNonzeroFrames > 0) Interlocked.Add(ref playedNonzeroSamples, playedNonzeroFrames);
            if (hadUnderrun) Interlocked.Increment(ref underruns);
        }

        void OnDisable()
        {
            AudioSettings.OnAudioConfigurationChanged -= OnAudioConfigurationChanged;
            Discard();
            if (source != null) source.Stop();
            if (silenceClip != null) Destroy(silenceClip);
            silenceClip = null;
            if (source != null) source.clip = null;
        }
    }
}
