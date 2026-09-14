using NUnit.Framework;

namespace Flylingual.Conversation.EditorTests
{
    public sealed class NeuralReadoutTests
    {
        [Test]
        public void AxisComparisonPreservesNullAndSignedValues()
        {
            var value = NeuralResponsePanel.Parse(@"{
                ""schemaVersion"":1,""fresh"":true,
                ""comparison"":{""eligible"":true,""changed"":true,""changedAxes"":[""forward""],
                    ""axes"":{""forward"":{""eligible"":true,""changed"":true,
                        ""currentMeanMv"":0.05,""previousMeanMv"":0.25,""deltaMeanMv"":-0.2,""directionalDeltaMv"":-0.2},
                    ""turn"":{""eligible"":false,""changed"":false,""deltaMeanMv"":null}}},
                ""current"":{""filteredRaw"":{""forward"":null,""turn"":-0.25}}}");
            Assert.That(value.comparison.changedAxes, Is.EqualTo(new[] { "forward" }));
            Assert.That(NeuralResponsePanel.Value(value.comparison.axes.forward.deltaMeanMv), Is.EqualTo(-0.2).Within(1e-9));
            Assert.That(double.IsNaN(NeuralResponsePanel.Value(value.comparison.axes.turn.deltaMeanMv)), Is.True);
            Assert.That(double.IsNaN(NeuralResponsePanel.Value(value.current.filteredRaw.forward)), Is.True);
            Assert.That(NeuralResponsePanel.Value(value.current.filteredRaw.turn), Is.EqualTo(-0.25));
        }

        [Test]
        public void ProvenanceAndAggregationSurviveConsumerParsing()
        {
            var value = NeuralResponsePanel.Parse(@"{
                ""selectedVncAggregation"":{""version"":""v1"",""method"":""cell_type_equal_weight_mean_delta_v"",""unit"":""mV""},
                ""readoutProvenance"":{
                    ""DNg100_L_Hz"":{""kind"":""neuron_readout"",""bodyId"":10045,""configuredStimulusGroups"":[""F""],""eligibleForDirectStimulation"":true},
                    ""DNg100_R_Hz"":{""kind"":""neuron_readout"",""bodyId"":10056,""configuredStimulusGroups"":[],""eligibleForDirectStimulation"":false},
                    ""DNp09_Hz"":{""kind"":""derived_metric"",""derivedFrom"":[""DNp09_L_Hz"",""DNp09_R_Hz""]},
                    ""DNa02Difference_Hz"":{""kind"":""derived_metric"",""derivedFrom"":[""DNa02_R_Hz"",""DNa02_L_Hz""]},
                    ""forward_raw"":{""kind"":""selected_vnc_aggregate"",""derivedFrom"":[""populationDeltaMv.forward""]}},
                ""calibration"":{""valid"":true,""artifactVerified"":true,""identityMatched"":true,""classificationReady"":{""changeTurn"":true}}}");
            Assert.That(value.selectedVncAggregation.method, Is.EqualTo("cell_type_equal_weight_mean_delta_v"));
            Assert.That(value.readoutProvenance.DNg100_L_Hz.bodyId, Is.EqualTo(10045));
            Assert.That(value.readoutProvenance.DNg100_L_Hz.configuredStimulusGroups, Is.EqualTo(new[] { "F" }));
            Assert.That(value.readoutProvenance.DNg100_R_Hz.eligibleForDirectStimulation, Is.False);
            Assert.That(value.readoutProvenance.DNp09_Hz.kind, Is.EqualTo("derived_metric"));
            Assert.That(value.readoutProvenance.DNa02Difference_Hz.derivedFrom.Length, Is.EqualTo(2));
            Assert.That(value.readoutProvenance.forward_raw.kind, Is.EqualTo("selected_vnc_aggregate"));
            Assert.That(value.calibration.classificationReady.changeTurn, Is.True);
            Assert.That(value.calibration.classificationReady.changeForward, Is.False);
            Assert.That(NeuralResponsePanel.ProvenanceText("DNg100 R", null), Is.EqualTo("DNg100 R: unknown"));
        }

        [TestCase(50, true)]
        [TestCase(100, true)]
        [TestCase(150, false)]
        public void FreshnessUsesBridge400MillisecondContract(double elapsed, bool expected)
        {
            var value = NeuralResponsePanel.Parse(@"{""fresh"":true,""ageMs"":300,""staleAfterMs"":400}");
            Assert.That(NeuralResponsePanel.IsFresh(value, elapsed), Is.EqualTo(expected));
            value.fresh = false;
            Assert.That(NeuralResponsePanel.IsFresh(value, 0), Is.False);
        }

        [TestCase("null")]
        [TestCase("0")]
        [TestCase("-1")]
        [TestCase("751")]
        [TestCase("\"invalid\"")]
        [TestCase("\"NaN\"")]
        public void ExplicitInvalidFreshnessDoesNotUseLegacyFallback(string limit)
        {
            var value = NeuralResponsePanel.Parse("{\"fresh\":true,\"ageMs\":0,\"staleAfterMs\":" + limit + "}");
            Assert.That(value.staleAfterMsPresent, Is.True);
            Assert.That(NeuralResponsePanel.IsFresh(value, 0), Is.False);
        }

        [Test]
        public void FreshEventCannotExtendOlderBodyObservation()
        {
            var value = NeuralResponsePanel.Parse(@"{""fresh"":true,""ageMs"":0,""staleAfterMs"":400,
                ""body"":{""fresh"":true,""correlated"":true,""ageMs"":390}}");
            Assert.That(NeuralResponsePanel.IsBodyFresh(value, 10), Is.True);
            Assert.That(NeuralResponsePanel.IsFresh(value, 20), Is.True);
            Assert.That(NeuralResponsePanel.IsBodyFresh(value, 20), Is.False);
            value.body.correlated = false;
            Assert.That(NeuralResponsePanel.IsBodyFresh(value, 0), Is.False);
        }

        [Test]
        public void OnlyMissingLimitUsesLegacy750AndInvalidAgesFailClosed()
        {
            var value = NeuralResponsePanel.Parse(@"{""fresh"":true,""ageMs"":300}");
            Assert.That(value.staleAfterMsPresent, Is.False);
            Assert.That(NeuralResponsePanel.IsFresh(value, 450), Is.True);
            Assert.That(NeuralResponsePanel.IsFresh(value, 451), Is.False);
            Assert.That(NeuralResponsePanel.IsFresh(value, -1), Is.False);
            Assert.That(NeuralResponsePanel.IsFresh(value, double.NaN), Is.False);
            value.ageMs = "-1";
            Assert.That(NeuralResponsePanel.IsFresh(value, 0), Is.False);
        }

        [Test]
        public void ArtifactVerifiedDoesNotImplyClassificationReady()
        {
            var calibration = new NeuralResponsePanel.Calibration { valid = true, artifactVerified = true, identityMatched = true };
            string text = NeuralResponsePanel.CalibrationText(calibration);
            Assert.That(text, Does.Not.Contain("Response F: ready"));
            Assert.That(text, Does.Not.Contain("Response F: 判定可能"));
            var comparison = new NeuralResponsePanel.Comparison { eligible = true, axes = new NeuralResponsePanel.ComparisonAxes {
                forward = new NeuralResponsePanel.AxisComparison { eligible = true, changed = true, deltaMeanMv = "-0.2" },
                turn = new NeuralResponsePanel.AxisComparison { eligible = true, changed = true, deltaMeanMv = "0.1" } } };
            text = NeuralResponsePanel.ComparisonText(comparison, calibration);
            Assert.That(text, Does.Not.Contain("above calibrated threshold"));
            Assert.That(text, Does.Not.Contain("校正閾値超"));
            calibration.classificationReady = new NeuralResponsePanel.ClassificationReady { changeTurn = true };
            text = NeuralResponsePanel.ComparisonText(comparison, calibration);
            string[] lines = text.Split('\n');
            Assert.That(lines[1], Does.Not.Contain("above calibrated threshold").And.Not.Contain("校正閾値超"));
            Assert.That(lines[2].Contains("above calibrated threshold") || lines[2].Contains("校正閾値超"), Is.True);
            calibration.identityMatched = false;
            text = NeuralResponsePanel.ComparisonText(comparison, calibration);
            Assert.That(text, Does.Not.Contain("above calibrated threshold").And.Not.Contain("校正閾値超"));
        }
        [Test]
        public void BothRelevantAxisDeltasAreVisibleWithoutCalibration()
        {
            var comparison = new NeuralResponsePanel.Comparison {
                eligible = true,
                axes = new NeuralResponsePanel.ComparisonAxes {
                    forward = new NeuralResponsePanel.AxisComparison { eligible = true, deltaMeanMv = "-0.2" },
                    turn = new NeuralResponsePanel.AxisComparison { eligible = true, deltaMeanMv = "0.1" }
                }
            };
            string result = NeuralResponsePanel.ComparisonText(comparison, null);
            Assert.That(result, Does.Contain("F Δ -0.2mV"));
            Assert.That(result, Does.Contain("T Δ 0.1mV"));
            Assert.That(result, Does.Not.Contain("同条件"));
            Assert.That(result.ToLowerInvariant(), Does.Not.Contain("same condition"));
        }

        [Test]
        public void OldProducerWithoutAxesRemainsReadable()
        {
            var value = NeuralResponsePanel.Parse(@"{""comparison"":{""eligible"":true},""current"":{""raw"":{""forward"":null,""turn"":0}}}");
            Assert.That(double.IsNaN(NeuralResponsePanel.Value(value.current.raw.forward)), Is.True);
            Assert.That(NeuralResponsePanel.Value(value.current.raw.turn), Is.EqualTo(0));
            Assert.DoesNotThrow(() => NeuralResponsePanel.ComparisonText(value.comparison, null));
        }
    }
}
