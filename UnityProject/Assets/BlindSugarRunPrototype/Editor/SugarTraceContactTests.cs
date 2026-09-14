using NUnit.Framework;

namespace Flylingual.BlindSugarRun.EditorTests
{
    public sealed class SugarTraceContactTests
    {
        [Test]
        public void FreshSupportedPassConsumesOncePerAttempt()
        {
            var state = new SugarTraceContactState();
            Assert.That(state.Sample(0, 0, 1.45, 0, false), Is.False);
            Assert.That(state.Sample(0, 0, 1.45, 0, true), Is.True);
            Assert.That(state.Sample(0, 0, 1.45, 0, true), Is.False);
            Assert.That(state.Sample(1, 1, 1.45, 0, true), Is.False);
            Assert.That(state.Sample(0, 0, 1.45, 0, true), Is.False);
            Assert.That(new SugarTraceContactState().Sample(0, 0, 1.45, 0, true), Is.True);
        }
        [TestCase(.36, 0, 1.45, 0)]
        [TestCase(0, -.36, 1.45, 0)]
        [TestCase(0, 0, 4, 0)]
        [TestCase(0, 0, -1, 0)]
        [TestCase(0, 0, 1.45, .2)]
        public void EdgeAirAndOtherSurfaceDoNotConsume(double x, double z, double height, double ground)
        {
            var state = new SugarTraceContactState();
            Assert.That(state.Sample(x, z, height, ground, true), Is.False);
            Assert.That(state.Consumed, Is.False);
        }
        [Test]
        public void MissingNumericDataCannotCreateContact()
        {
            var state = new SugarTraceContactState();
            Assert.That(state.Sample(double.NaN, 0, 1, 0, true), Is.False);
            Assert.That(state.Sample(0, 0, double.NaN, 0, true), Is.False);
            Assert.That(state.Sample(0, 0, 1, double.PositiveInfinity, true), Is.False);
        }
    }
}
