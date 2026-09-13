namespace Flylingual.BlindSugarRun
{
    /// <summary>Pure time/identity gate, independently verifiable without physics or an API.</summary>
    public sealed class BlindSugarRunGoalStability
    {
        double stableSince = -1, lastCheck = -1;
        int epoch = -1, generation = -1;
        public double StableSeconds { get; private set; }

        public bool Sample(double now, bool valid, int currentEpoch, int currentGeneration)
        {
            if (currentEpoch != epoch || currentGeneration != generation)
            { Reset(); epoch = currentEpoch; generation = currentGeneration; }
            if (!valid || double.IsNaN(now) || double.IsInfinity(now) || now < 0)
            { Reset(); return false; }
            if (lastCheck < 0 || now < lastCheck || now - lastCheck > .25) stableSince = now;
            if (stableSince < 0) stableSince = now;
            lastCheck = now;
            StableSeconds = now - stableSince;
            return StableSeconds >= 1;
        }
        public void Reset() { stableSince = lastCheck = -1; StableSeconds = 0; }
    }
}
