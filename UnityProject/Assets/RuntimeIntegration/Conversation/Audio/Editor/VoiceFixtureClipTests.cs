using System;
using System.IO;
using System.Security.Cryptography;
using NUnit.Framework;

namespace Flylingual.Conversation.EditorTests
{
    public sealed class VoiceFixtureClipTests
    {
        string temporaryPath;

        [TearDown]
        public void TearDown()
        {
            if (!string.IsNullOrEmpty(temporaryPath) && File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }

        [Test]
        public void Load_Stereo48kHz_ConvertsToOneMono100msChunk()
        {
            var pcm = new byte[4800 * 2 * sizeof(short)]; // 100 ms, stereo, 48 kHz
            for (int i = 0; i < pcm.Length; i += 4) { pcm[i] = 0xff; pcm[i + 1] = 0x3f; }
            var clip = Load(WriteWav(2, 48000, pcm, includeOddUnknownChunk: true));

            Assert.That(clip.SourceChannels, Is.EqualTo(2));
            Assert.That(clip.SourceSampleRate, Is.EqualTo(48000));
            Assert.That(clip.DurationSeconds, Is.EqualTo(.1d).Within(.000001d));
            Assert.That(clip.Chunks.Length, Is.EqualTo(1));
            Assert.That(clip.Chunks[0].Length, Is.EqualTo(PcmStreamConverter.ChunkSamples * sizeof(short)));
            Assert.That(clip.Chunks[0][0], Is.Not.EqualTo(0));
        }

        [Test]
        public void Load_PartialChunk_PadsTailInsteadOfDroppingIt()
        {
            var pcm = new byte[1200 * sizeof(short)]; // 50 ms at 24 kHz
            for (int i = 0; i < pcm.Length; i += 2) { pcm[i] = 0xff; pcm[i + 1] = 0x3f; }
            var clip = Load(WriteWav(1, 24000, pcm));

            Assert.That(clip.Chunks.Length, Is.EqualTo(1));
            Assert.That(clip.Chunks[0][0], Is.Not.EqualTo(0));
            Assert.That(clip.Chunks[0][clip.Chunks[0].Length - 2], Is.EqualTo(0));
            Assert.That(clip.Chunks[0][clip.Chunks[0].Length - 1], Is.EqualTo(0));
        }

        [Test]
        public void Load_RejectsDurationThatWouldExpandUnboundedly()
        {
            Assert.That(() => Load(WriteWav(1, 1, new byte[64])), Throws.TypeOf<InvalidDataException>());
        }

        [Test]
        public void Load_RejectsShaMismatchAndTruncatedChunks()
        {
            string malformed = Path.GetTempFileName();
            try
            {
                File.WriteAllBytes(malformed, new byte[] { (byte)'R', (byte)'I', (byte)'F', (byte)'F' });
                Assert.That(() => VoiceFixtureClip.Load(malformed, new string('0', 64)), Throws.TypeOf<InvalidDataException>());
            }
            finally { File.Delete(malformed); }

            byte[] wav = WriteWav(1, 24000, new byte[4800]);
            temporaryPath = Path.GetTempFileName();
            File.WriteAllBytes(temporaryPath, wav);
            Assert.That(() => VoiceFixtureClip.Load(temporaryPath, new string('0', 64)), Throws.TypeOf<InvalidDataException>());
        }

        VoiceFixtureClip Load(byte[] wav)
        {
            if (!string.IsNullOrEmpty(temporaryPath) && File.Exists(temporaryPath)) File.Delete(temporaryPath);
            temporaryPath = Path.GetTempFileName();
            File.WriteAllBytes(temporaryPath, wav);
            return VoiceFixtureClip.Load(temporaryPath, Sha256(wav));
        }

        static byte[] WriteWav(int channels, int sampleRate, byte[] pcm, bool includeOddUnknownChunk = false)
        {
            using (var stream = new MemoryStream())
            using (var writer = new BinaryWriter(stream))
            {
                writer.Write(new byte[] { (byte)'R', (byte)'I', (byte)'F', (byte)'F' });
                writer.Write(0); // filled below
                writer.Write(new byte[] { (byte)'W', (byte)'A', (byte)'V', (byte)'E' });
                writer.Write(new byte[] { (byte)'f', (byte)'m', (byte)'t', (byte)' ' });
                writer.Write(16);
                writer.Write((short)1);
                writer.Write((short)channels);
                writer.Write(sampleRate);
                writer.Write(sampleRate * channels * sizeof(short));
                writer.Write((short)(channels * sizeof(short)));
                writer.Write((short)16);
                if (includeOddUnknownChunk)
                {
                    writer.Write(new byte[] { (byte)'J', (byte)'U', (byte)'N', (byte)'K' });
                    writer.Write(1);
                    writer.Write((byte)7);
                    writer.Write((byte)0); // RIFF odd-size padding
                }
                writer.Write(new byte[] { (byte)'d', (byte)'a', (byte)'t', (byte)'a' });
                writer.Write(pcm.Length);
                writer.Write(pcm);
                writer.Flush();
                stream.Position = 4;
                writer.Write((int)stream.Length - 8);
                writer.Flush();
                return stream.ToArray();
            }
        }

        static string Sha256(byte[] bytes)
        {
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", string.Empty).ToLowerInvariant();
        }
    }
}
