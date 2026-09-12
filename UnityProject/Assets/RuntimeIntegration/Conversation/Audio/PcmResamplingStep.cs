using System;

namespace Flylingual.Conversation
{
    /// <summary>Allocation-free source-frame advancement shared by the audio callback and pure tests.</summary>
    public static class PcmResamplingStep
    {
        public static int Consume(ref double phase, int queuedSamples, int inputRate, int outputRate)
        {
            if (queuedSamples < 2 || inputRate <= 0 || outputRate <= 0) return 0;
            phase += (double)inputRate / outputRate;
            int wanted = (int)phase;
            int maximum = queuedSamples - 1;
            int consume = Math.Min(wanted, maximum);
            phase -= consume;
            // When the callback runs out of look-ahead, do not carry a phase >= 1
            // into the next network packet. That would interpolate outside [a, b].
            if (consume < wanted) phase = 0d;
            return consume;
        }
    }
}
