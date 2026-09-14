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
                ""readoutProvenance"":{""DNg100_L_Hz"":""stimulated_input_neuron"",""DNg100_R_Hz"":""stimulated_input_neuron"",
                    ""DNa02_L_Hz"":""non_stimulated_selected_readout"",""DNp09_R_Hz"":""non_stimulated_selected_readout""},
                ""calibration"":{""valid"":false,""status"":""artifact_missing""}}");
            Assert.That(value.selectedVncAggregation.method, Is.EqualTo("cell_type_equal_weight_mean_delta_v"));
            Assert.That(value.readoutProvenance.DNg100_L_Hz, Is.EqualTo("stimulated_input_neuron"));
            Assert.That(value.readoutProvenance.DNg100_R_Hz, Is.EqualTo("stimulated_input_neuron"));
            Assert.That(value.readoutProvenance.DNa02_L_Hz, Is.EqualTo("non_stimulated_selected_readout"));
            Assert.That(value.readoutProvenance.DNp09_R_Hz, Is.EqualTo("non_stimulated_selected_readout"));
            Assert.That(value.calibration.valid, Is.False);
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
