using System;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Attempt-owned contact latch; reconnects do not reset consumption.</summary>
    public sealed class SugarTraceContactState
    {
        public bool Consumed { get; private set; }
        public bool Sample(double normalizedX, double normalizedZ, double bodyHeight, double groundOffset, bool freshGround)
        {
            if (Consumed || !freshGround || !(Math.Abs(normalizedX) <= .35) || !(Math.Abs(normalizedZ) <= .35)
                || !(bodyHeight >= 0 && bodyHeight <= 3.5) || !(Math.Abs(groundOffset) <= .15)) return false;
            Consumed = true;
            return true;
        }
    }
}
