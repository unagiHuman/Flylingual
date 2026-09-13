// Pure timing regression. This does not simulate Unity physics or a Brain connection.
using System;
using Flylingual.BlindSugarRun;

static class GoalStabilityTests
{
    static int checks;
    static void Check(bool condition, string name)
    {
        checks++;
        if (!condition) throw new Exception(name);
    }
    static void Main()
    {
        var gate = new BlindSugarRunGoalStability();
        for (int i = 0; i < 10; i++) Check(!gate.Sample(i / 10d, true, 1, 1), "premature goal");
        Check(gate.Sample(1, true, 1, 1), "one second continuous stability");
        Check(!gate.Sample(1.1, false, 1, 1), "exit or motion resets stability");
        Check(gate.StableSeconds == 0, "invalid observation clears time");
        Check(!gate.Sample(1.2, true, 1, 1), "reentry starts over");
        for (int i = 13; i <= 20; i++) gate.Sample(i / 10d, true, 1, 1);
        Check(!gate.Sample(2.1, true, 2, 1), "epoch reset");
        Check(gate.StableSeconds == 0, "epoch clears time");
        gate.Sample(2.2, true, 2, 1);
        Check(!gate.Sample(2.3, true, 2, 2), "voice generation reset");
        Check(gate.StableSeconds == 0, "generation clears time");
        Check(!gate.Sample(3, true, 2, 2), "missing samples do not accumulate");
        Check(gate.StableSeconds == 0, "gap resets time");
        gate.Sample(3.1, true, 2, 2);
        Check(!gate.Sample(2.5, true, 2, 2), "clock reversal resets time");
        foreach (double value in new[] { double.NaN, double.PositiveInfinity, -1d })
        {
            Check(!gate.Sample(value, true, 2, 2), "invalid clock rejected");
            Check(gate.StableSeconds == 0, "invalid clock clears time");
        }
        gate.Reset();
        for (int i = 0; i <= 11; i++) gate.Sample(10 + i / 10d, true, 2, 2);
        Check(gate.StableSeconds >= 1, "new stable interval completes");
        Console.WriteLine("PASS: " + checks + " pure goal timing checks");
    }
}
