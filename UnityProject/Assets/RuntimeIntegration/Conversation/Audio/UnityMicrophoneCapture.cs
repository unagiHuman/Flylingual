using System;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Main-thread microphone capture. PTT-off data is always discarded before conversion.</summary>
    public sealed class UnityMicrophoneCapture : MonoBehaviour
    {
        const int RingSeconds = 2;
        const float StallSeconds = 1.5f;
        const int PreferredSampleRate = 48000;
        const string DeviceUnavailable = "microphone_device_unavailable";
        const string StartFailed = "microphone_start_failed";
        const string RecordingStopped = "microphone_recording_stopped";
        const string PositionUnavailable = "microphone_position_unavailable";
        const string CaptureStalled = "microphone_capture_stalled";
        const string ClipReadFailed = "microphone_clip_read_failed";

        public event Action<byte[]> PcmChunk;
        public string[] Devices => Microphone.devices;
        public float Rms { get; private set; }
        public string Error { get; private set; }
        public int SampleRate { get; private set; }
        public bool IsCapturing => clip != null && Microphone.IsRecording(deviceName);

        AudioClip clip;
        string deviceName;
        PcmStreamConverter converter;
        float[] readBuffer = Array.Empty<float>();
        int readPosition;
        int lastPosition = -1;
        float lastProgressAt;
        bool transmitting;

        void Awake() => converter = new PcmStreamConverter();

        public bool StartCapture(string device)
        {
            StopCapture();
            Error = null;
            deviceName = device;
            if (deviceName != null && Array.IndexOf(Microphone.devices, deviceName) < 0)
            {
                Error = DeviceUnavailable;
                return false;
            }
            try
            {
                int requestedRate = PreferredRate(deviceName);
                clip = Microphone.Start(deviceName, true, RingSeconds, requestedRate);
                if (clip == null)
                {
                    Error = StartFailed;
                    return false;
                }
                SampleRate = clip.frequency;
                readPosition = Math.Max(0, Microphone.GetPosition(deviceName));
                lastPosition = readPosition;
                lastProgressAt = Time.unscaledTime;
                converter.Reset();
                return true;
            }
            catch (Exception)
            {
                Error = StartFailed;
                StopCapture();
                return false;
            }
        }

        static int PreferredRate(string device)
        {
            Microphone.GetDeviceCaps(device, out int minimum, out int maximum);
            if (maximum == 0 || (minimum <= PreferredSampleRate && PreferredSampleRate <= maximum)) return PreferredSampleRate;
            const int fallback = 44100;
            if (minimum <= fallback && fallback <= maximum) return fallback;
            return Math.Max(1, Math.Max(minimum, Math.Min(maximum, fallback)));
        }

        public void StopCapture()
        {
            AudioClip capturedClip = clip;
            try { if (capturedClip != null && Microphone.IsRecording(deviceName)) Microphone.End(deviceName); }
            catch (Exception) { }
            clip = null;
            readPosition = 0;
            lastPosition = -1;
            SampleRate = 0;
            Rms = 0f;
            transmitting = false;
            converter?.Reset();
            if (capturedClip != null) Destroy(capturedClip);
        }

        public void SetTransmitting(bool value)
        {
            if (transmitting == value) return;
            transmitting = value;
            converter.Reset();
            if (clip != null) readPosition = Math.Max(0, Microphone.GetPosition(deviceName));
        }

        void Update()
        {
            if (clip == null) return;
            if (!Microphone.IsRecording(deviceName))
            {
                Error = RecordingStopped;
                StopCapture();
                return;
            }
            int position = Microphone.GetPosition(deviceName);
            if (position < 0)
            {
                Error = PositionUnavailable;
                return;
            }
            if (position != lastPosition)
            {
                lastPosition = position;
                lastProgressAt = Time.unscaledTime;
            }
            else if (Time.unscaledTime - lastProgressAt > StallSeconds)
            {
                Error = CaptureStalled;
            }

            int frames = position >= readPosition ? position - readPosition : clip.samples - readPosition + position;
            if (frames == 0) return;
            if (!transmitting)
            {
                readPosition = position;
                Rms = 0f;
                converter.Reset();
                return;
            }
            ReadFrames(readPosition, Math.Min(frames, clip.samples - readPosition));
            int remainder = frames - Math.Min(frames, clip.samples - readPosition);
            if (remainder > 0) ReadFrames(0, remainder);
            readPosition = position;
        }

        void ReadFrames(int offsetFrames, int frames)
        {
            int sampleCount = frames * clip.channels;
            if (readBuffer.Length < sampleCount) readBuffer = new float[sampleCount];
            if (!clip.GetData(readBuffer, offsetFrames))
            {
                Error = ClipReadFailed;
                return;
            }
            double sum = 0;
            for (int i = 0; i < sampleCount; i++) sum += readBuffer[i] * readBuffer[i];
            Rms = sampleCount == 0 ? 0f : (float)Math.Sqrt(sum / sampleCount);
            foreach (byte[] pcm in converter.Push(readBuffer, sampleCount, clip.channels, clip.frequency)) PcmChunk?.Invoke(pcm);
        }

        void OnDisable() => StopCapture();
    }
}
