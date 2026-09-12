using NUnit.Framework;

namespace Flylingual.Conversation.EditorTests
{
    public sealed class PcmStreamConverterTests
    {
        [Test]
        public void Stereo48kHz_ProducesContinuous100msPcmChunks()
        {
            var converter = new PcmStreamConverter();
            var samples = new float[9600]; // 100 ms, stereo, 48 kHz
            for (int i = 0; i < samples.Length; i += 2) { samples[i] = 1f; samples[i + 1] = -1f; }
            var chunks = converter.Push(samples, samples.Length, 2, 48000);
            Assert.That(chunks.Count, Is.EqualTo(1));
            Assert.That(chunks[0].Length, Is.EqualTo(PcmStreamConverter.ChunkSamples * 2));
            Assert.That(chunks[0][0], Is.EqualTo(0));
            Assert.That(chunks[0][1], Is.EqualTo(0));
        }

        [Test]
        public void Reset_DropsPartialChunk()
        {
            var converter = new PcmStreamConverter();
            var samples = new float[1200];
            converter.Push(samples, samples.Length, 1, 24000);
            converter.Reset();
            var result = converter.Push(samples, samples.Length, 1, 24000);
            Assert.That(result.Count, Is.EqualTo(0));
        }

        [Test]
        public void HighRateTinyBlocks_RemainBoundedAndEventuallyProduceChunks()
        {
            var converter = new PcmStreamConverter(4);
            int produced = 0;
            for (int i = 0; i < 5000; i++)
                produced += converter.Push(new[] { 0.25f, 0.25f }, 2, 1, 96000).Count;
            Assert.That(produced, Is.GreaterThan(0));
        }

        [Test]
        public void DownsampleOutput_ResetsPhaseWhenLookaheadIsExhausted()
        {
            double phase = 0d;
            int consumed = PcmResamplingStep.Consume(ref phase, 2, 24000, 12000);
            Assert.That(consumed, Is.EqualTo(1));
            Assert.That(phase, Is.EqualTo(0d));
        }
    }
}
