using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;

namespace Flylingual.Conversation
{
    /// <summary>Validated WAV fixture converted to the controller's 24 kHz mono PCM chunks.</summary>
    public sealed class VoiceFixtureClip
    {
        const int MaxFileBytes = 8 * 1024 * 1024;
        const int MaxChannels = 8;
        const int MaxSampleRate = 192000;
        const double MaxDurationSeconds = 30;

        public byte[][] Chunks { get; private set; }
        public string Sha256 { get; private set; }
        public double DurationSeconds { get; private set; }
        public int SourceSampleRate { get; private set; }
        public int SourceChannels { get; private set; }

        VoiceFixtureClip() { }

        public static VoiceFixtureClip Load(string path, string expectedSha256)
        {
            if (string.IsNullOrEmpty(path)) throw new ArgumentException("Fixture WAV path is required.", nameof(path));
            if (string.IsNullOrEmpty(expectedSha256)) throw new ArgumentException("Fixture WAV SHA-256 is required.", nameof(expectedSha256));
            var file = new FileInfo(path);
            if (!file.Exists) throw new FileNotFoundException("Fixture WAV was not found.", path);
            if (file.Length < 12 || file.Length > MaxFileBytes) throw new InvalidDataException("Fixture WAV size is invalid.");

            byte[] bytes = File.ReadAllBytes(path);
            string sha256 = ComputeSha256(bytes);
            if (!string.Equals(sha256, expectedSha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Fixture WAV SHA-256 does not match its manifest.");
            return Parse(bytes, sha256);
        }

        static VoiceFixtureClip Parse(byte[] bytes, string sha256)
        {
            if (!HasFourCc(bytes, 0, "RIFF") || !HasFourCc(bytes, 8, "WAVE"))
                throw new InvalidDataException("Fixture must be a RIFF/WAVE file.");
            uint declaredSize = ReadUInt32(bytes, 4);
            if ((ulong)declaredSize + 8UL != (ulong)bytes.Length)
                throw new InvalidDataException("Fixture RIFF size does not match the file.");

            int position = 12;
            bool hasFormat = false;
            int channels = 0, sampleRate = 0, blockAlign = 0;
            var data = new List<byte>();
            while (position < bytes.Length)
            {
                if (bytes.Length - position < 8) throw new InvalidDataException("Fixture WAV chunk header is truncated.");
                uint size = ReadUInt32(bytes, position + 4);
                int content = position + 8;
                ulong endLong = (ulong)content + size;
                if (endLong > (ulong)bytes.Length) throw new InvalidDataException("Fixture WAV chunk is truncated.");
                int end = (int)endLong;
                if (HasFourCc(bytes, position, "fmt "))
                {
                    if (hasFormat || size < 16) throw new InvalidDataException("Fixture WAV format chunk is invalid.");
                    ushort format = ReadUInt16(bytes, content);
                    channels = ReadUInt16(bytes, content + 2);
                    sampleRate = checked((int)ReadUInt32(bytes, content + 4));
                    uint byteRate = ReadUInt32(bytes, content + 8);
                    blockAlign = ReadUInt16(bytes, content + 12);
                    ushort bitsPerSample = ReadUInt16(bytes, content + 14);
                    if (format != 1 || bitsPerSample != 16 || channels < 1 || channels > MaxChannels
                        || sampleRate < 1 || sampleRate > MaxSampleRate || blockAlign != channels * sizeof(short)
                        || byteRate != (uint)(sampleRate * blockAlign))
                        throw new InvalidDataException("Fixture must be PCM16 with a valid format.");
                    hasFormat = true;
                }
                else if (HasFourCc(bytes, position, "data"))
                {
                    if (size > MaxFileBytes || data.Count > MaxFileBytes - (int)size)
                        throw new InvalidDataException("Fixture audio data is too large.");
                    for (int i = content; i < end; i++) data.Add(bytes[i]);
                }

                position = end;
                if ((size & 1) != 0)
                {
                    if (position >= bytes.Length) throw new InvalidDataException("Fixture WAV padding is truncated.");
                    position++;
                }
            }

            if (!hasFormat || data.Count == 0 || data.Count % blockAlign != 0)
                throw new InvalidDataException("Fixture WAV has no complete PCM16 data frames.");
            int frames = data.Count / blockAlign;
            if (frames / (double)sampleRate > MaxDurationSeconds)
                throw new InvalidDataException("Fixture audio exceeds 30 seconds.");
            var samples = new float[data.Count / sizeof(short)];
            for (int i = 0, sample = 0; i < data.Count; i += 2, sample++)
                samples[sample] = (short)(data[i] | (data[i + 1] << 8)) / 32768f;

            var converter = new PcmStreamConverter();
            var chunks = new List<byte[]>();
            AddChunks(chunks, converter.Push(samples, samples.Length, channels, sampleRate));
            int requiredChunks = checked((int)Math.Ceiling(frames * (double)PcmStreamConverter.TargetSampleRate
                / sampleRate / PcmStreamConverter.ChunkSamples));
            // Push source-rate silence so the converter flushes its partial 100 ms output.
            // The final fixture chunk remains full sized, with the tail explicitly silent.
            int paddingFrames = Math.Max(2, (int)Math.Ceiling(sampleRate / 10d) + 1);
            var silence = new float[paddingFrames * channels];
            while (chunks.Count < requiredChunks)
            {
                AddChunks(chunks, converter.Push(silence, silence.Length, channels, sampleRate));
                if (chunks.Count > requiredChunks + 1) throw new InvalidDataException("Fixture conversion produced an invalid chunk count.");
            }

            return new VoiceFixtureClip
            {
                Chunks = chunks.ToArray(),
                Sha256 = sha256,
                DurationSeconds = frames / (double)sampleRate,
                SourceSampleRate = sampleRate,
                SourceChannels = channels,
            };
        }

        static void AddChunks(List<byte[]> destination, IReadOnlyList<byte[]> source)
        {
            for (int i = 0; i < source.Count; i++) destination.Add(source[i]);
        }

        static string ComputeSha256(byte[] bytes)
        {
            using (var hash = SHA256.Create())
            {
                var value = hash.ComputeHash(bytes);
                return BitConverter.ToString(value).Replace("-", string.Empty).ToLowerInvariant();
            }
        }

        static bool HasFourCc(byte[] bytes, int offset, string value)
        {
            if (offset < 0 || offset + 4 > bytes.Length) return false;
            return bytes[offset] == value[0] && bytes[offset + 1] == value[1]
                && bytes[offset + 2] == value[2] && bytes[offset + 3] == value[3];
        }

        static ushort ReadUInt16(byte[] bytes, int offset)
        {
            if (offset < 0 || offset + 2 > bytes.Length) throw new InvalidDataException("Fixture WAV field is truncated.");
            return (ushort)(bytes[offset] | (bytes[offset + 1] << 8));
        }

        static uint ReadUInt32(byte[] bytes, int offset)
        {
            if (offset < 0 || offset + 4 > bytes.Length) throw new InvalidDataException("Fixture WAV field is truncated.");
            return (uint)(bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24));
        }
    }
}
