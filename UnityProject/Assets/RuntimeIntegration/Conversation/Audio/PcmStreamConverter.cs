using System;
using System.Collections.Generic;

namespace Flylingual.Conversation
{
    /// <summary>Continuously converts an interleaved microphone stream to 24 kHz mono PCM16LE.</summary>
    public sealed class PcmStreamConverter
    {
        public const int TargetSampleRate = 24000;
        public const int ChunkSamples = 2400;

        readonly int maxCarryFrames;
        float[] carry = Array.Empty<float>();
        float[] chunk = new float[ChunkSamples];
        int carryFrames;
        int channels;
        int sampleRate;
        int chunkCount;
        double sourcePosition;

        public PcmStreamConverter(int maxCarryFrames = TargetSampleRate)
        {
            if (maxCarryFrames < 2) throw new ArgumentOutOfRangeException(nameof(maxCarryFrames));
            this.maxCarryFrames = maxCarryFrames;
        }

        public void Reset()
        {
            carryFrames = 0;
            channels = 0;
            sampleRate = 0;
            chunkCount = 0;
            sourcePosition = 0;
        }

        public IReadOnlyList<byte[]> Push(float[] interleaved, int sampleCount, int inputChannels, int inputSampleRate)
        {
            if (interleaved == null) throw new ArgumentNullException(nameof(interleaved));
            if (sampleCount < 0 || sampleCount > interleaved.Length) throw new ArgumentOutOfRangeException(nameof(sampleCount));
            if (inputChannels <= 0 || inputSampleRate <= 0 || sampleCount % inputChannels != 0)
                throw new ArgumentException("Input must contain complete interleaved sample frames.");
            if (sampleCount == 0) return Array.Empty<byte[]>();
            if (channels != 0 && (channels != inputChannels || sampleRate != inputSampleRate)) Reset();
            channels = inputChannels;
            sampleRate = inputSampleRate;

            int inputFrames = sampleCount / inputChannels;
            int totalFrames = carryFrames + inputFrames;
            float[] source = new float[totalFrames * channels];
            if (carryFrames > 0) Array.Copy(carry, 0, source, 0, carryFrames * channels);
            Array.Copy(interleaved, 0, source, carryFrames * channels, sampleCount);

            var completed = new List<byte[]>();
            double step = (double)sampleRate / TargetSampleRate;
            while (sourcePosition + 1d < totalFrames)
            {
                int lower = (int)sourcePosition;
                float fraction = (float)(sourcePosition - lower);
                float monoA = Mono(source, lower * channels, channels);
                float monoB = Mono(source, (lower + 1) * channels, channels);
                chunk[chunkCount++] = monoA + (monoB - monoA) * fraction;
                sourcePosition += step;
                if (chunkCount == ChunkSamples)
                {
                    completed.Add(ToPcm16(chunk));
                    chunkCount = 0;
                }
            }

            // A source rate above the target can step beyond this small input block.
            // Retain no nonexistent source frames while preserving the fractional/overrun
            // position for the next block.
            int retainStart = Math.Min(totalFrames, Math.Max(0, (int)Math.Floor(sourcePosition)));
            int retainedFrames = totalFrames - retainStart;
            if (retainedFrames > maxCarryFrames)
            {
                retainStart = totalFrames - maxCarryFrames;
                retainedFrames = maxCarryFrames;
                sourcePosition = retainStart;
            }
            EnsureCarryCapacity(retainedFrames * channels);
            Array.Copy(source, retainStart * channels, carry, 0, retainedFrames * channels);
            carryFrames = retainedFrames;
            sourcePosition -= retainStart;
            return completed;
        }

        static float Mono(float[] samples, int offset, int channelCount)
        {
            float sum = 0f;
            for (int channel = 0; channel < channelCount; channel++) sum += samples[offset + channel];
            return sum / channelCount;
        }

        void EnsureCarryCapacity(int count)
        {
            if (carry.Length >= count) return;
            carry = new float[Math.Max(count, maxCarryFrames * Math.Max(channels, 1))];
        }

        static byte[] ToPcm16(float[] samples)
        {
            var bytes = new byte[samples.Length * 2];
            for (int i = 0; i < samples.Length; i++)
            {
                float clamped = Math.Max(-1f, Math.Min(1f, samples[i]));
                short value = (short)Math.Round(clamped * short.MaxValue);
                bytes[i * 2] = (byte)value;
                bytes[i * 2 + 1] = (byte)(value >> 8);
            }
            return bytes;
        }
    }
}
