using System;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.UIElements;
using Flylingual.PlayScreen;

namespace Flylingual.Conversation
{
    /// <summary>Read-only selected neural measurements; never produces motion.</summary>
    public sealed class NeuralResponsePanel : VisualElement
    {
        readonly Label readings = new Label();
        readonly Label legend = new Label();
        readonly Foldout details = new Foldout { value = false };
        readonly Label detailReadings = new Label();
        readonly VisualElement plot = new VisualElement();
        readonly VisualElement motorPlot = new VisualElement();
        Observation shown;
        bool currentFresh;
        public NeuralResponsePanel()
        {
            style.flexShrink = 0; style.paddingTop = 5;
            readings.style.fontSize = 11; readings.style.whiteSpace = WhiteSpace.Normal;
            legend.style.fontSize = 10; legend.style.whiteSpace = WhiteSpace.Normal;
            detailReadings.style.fontSize = 11; detailReadings.style.whiteSpace = WhiteSpace.Normal;
            plot.style.height = 42; plot.generateVisualContent += Draw;
            motorPlot.style.height = 30; motorPlot.generateVisualContent += DrawMotor;
            details.Add(detailReadings);
            Add(readings); Add(plot); Add(motorPlot); Add(legend); Add(details);
        }
        public void Refresh(ConversationSessionController controller)
        {
            shown = controller == null ? null : controller.NeuralResponse;
            style.display = controller != null && controller.NeuralResponseAvailable ? DisplayStyle.Flex : DisplayStyle.None;
            double receivedAge = controller == null ? double.PositiveInfinity :
                (Time.realtimeSinceStartupAsDouble - controller.NeuralResponseReceivedAt) * 1000;
            double sourceAge = Value(shown?.ageMs);
            double age = sourceAge + receivedAge;
            currentFresh = shown != null && shown.fresh && !double.IsNaN(age) && age <= 750;
            var now = currentFresh ? shown.current : null;
            string unknown = "unknown";
            string applied = now != null && now.stimulusApplied ? now.appliedRequestId ?? unknown : unknown;
            if (now != null && !now.stimulusApplied && !string.IsNullOrEmpty(now.requestedRequestId)
                && now.requestedRequestId != unknown) applied = GameLanguage.Text("受付済・適用待ち", "Accepted / pending application");
            var body = currentFresh && shown.body != null && shown.body.fresh && shown.body.correlated ? shown.body : null;
            readings.text = GameLanguage.Text("要求 ", "Requested ") + (now?.requestedAction ?? unknown) + GameLanguage.Text(" → 適用 ", " → Applied ") + applied +
                "\nVNC F " + Format(now?.raw?.forward) + "mV / T " + Format(now?.raw?.turn) + "mV" +
                "  motor " + Format(now?.motor?.forward) + " / " + Format(now?.motor?.turn) +
                "\n" + (shown?.identity?.backendId ?? unknown) + " " + (shown?.mode ?? unknown) + " | age " +
                (double.IsNaN(age) || double.IsInfinity(age) ? unknown : age.ToString("0", CultureInfo.InvariantCulture) + "ms") +
                (currentFresh ? "" : GameLanguage.Text(" | 現在値unknown", " | Current unknown"));
            bool knownAggregation = shown?.selectedVncAggregation?.method == "cell_type_equal_weight_mean_delta_v";
            legend.text = knownAggregation ? GameLanguage.Text("選択VNCの細胞型均等ΔV", "Selected VNC class-balanced ΔV")
                : GameLanguage.Text("選択readout（集計方法unknown）", "Selected readout (aggregation unknown)");
            legend.text += GameLanguage.Text("。青=前進 / 橙=旋回 / 薄線=前回。上:mV / 下:motor±1。",
                ". Blue=forward / orange=turn / faded=previous. Top:mV / bottom:motor±1.");
            if (shown != null) legend.text += " raw ±" + RawScale().ToString("0.###", CultureInfo.InvariantCulture) + "mV";
            details.text = GameLanguage.Text("測定と比較の詳細", "Measurement and comparison details");
            detailReadings.text = "Filtered raw mV F " + Format(now?.filteredRaw?.forward) + " / T " + Format(now?.filteredRaw?.turn) +
                "\npop ΔmV F L/R " + Format(now?.populationDeltaMv?.forward?.L) + "/" + Format(now?.populationDeltaMv?.forward?.R) +
                "  T L/R " + Format(now?.populationDeltaMv?.turn?.L) + "/" + Format(now?.populationDeltaMv?.turn?.R) +
                GameLanguage.Text("\n身体 m/s ", "\nBody m/s ") + Format(body?.horizontalSpeed) + GameLanguage.Text("  前方 ", "  Forward ") + Format(body?.forwardSpeed) +
                "  yaw °/s " + Format(body?.yawRateDegPerSec) +
                GameLanguage.Text("\n身体対応seq ", "\nBody matched seq ") + (body?.brainSequence ?? unknown) +
                " / " + (shown?.sequence ?? unknown) + GameLanguage.Text(" (現行) Δ脳内 ", " (current) Δbrain ") + Format(body?.brainTimeOffsetMs) + "ms\n" +
                ComparisonText(currentFresh ? shown?.comparison : null, currentFresh ? shown?.calibration : null) +
                GameLanguage.Text("\n原因未確定。刺激系列は固定していません。身体動作・感情の証明ではありません。",
                    "\nCause unresolved. Stimulus sequence not controlled. Body motion and feelings are unverified.") +
                GameLanguage.Text("\n除外した適用確認窓の終端から200脳内ms。yawとmotorの符号対応は未校正。",
                    "\n200 brain ms after the excluded application window. Yaw-to-motor sign uncalibrated.");
            if (shown?.readoutProvenance?.DNg100_L_Hz == "stimulated_input_neuron" &&
                shown?.readoutProvenance?.DNg100_R_Hz == "stimulated_input_neuron")
                detailReadings.text += GameLanguage.Text("\nDNg100: 直接刺激する入力ニューロンの観測。独立した下流応答ではありません。",
                    "\nDNg100: directly stimulated input neurons; not independent downstream response.");
            plot.MarkDirtyRepaint(); motorPlot.MarkDirtyRepaint();
        }

        public static string ComparisonText(Comparison comparison, Calibration calibration)
        {
            if (comparison == null || !comparison.eligible)
                return GameLanguage.Text("比較不可: ", "Comparison unavailable: ") + (comparison?.reason ?? "unknown");
            string result = GameLanguage.Text("前回の比較可能な同一Action観測との差", "Difference from a comparable previous same-Action observation");
            foreach (string axis in new[] { "forward", "turn" })
            {
                var value = axis == "forward" ? comparison.axes?.forward : comparison.axes?.turn;
                if (value == null || !value.eligible) continue;
                result += "\n" + (axis == "forward" ? "F" : "T") + " Δ " + Format(value.deltaMeanMv) + "mV";
                if (calibration != null && calibration.valid && value.changed)
                    result += GameLanguage.Text("（校正閾値超）", " (above calibrated threshold)");
            }
            if (calibration == null || !calibration.valid)
                result += GameLanguage.Text("\n未校正: 数値のみ。強弱・有意な変化は判定しません。",
                    "\nUncalibrated: numbers only; no strength or significant-change classification.");
            return result;
        }
        void Draw(MeshGenerationContext context)
        {
            if (shown == null) return;
            double scale = RawScale();
            DrawCurve(context, shown.previousCurve, scale, .3f, plot.contentRect, false);
            if (currentFresh) DrawCurve(context, shown.currentCurve, scale, 1, plot.contentRect, false);
        }
        double RawScale()
        {
            double scale = .001;
            foreach (var curve in new[] { shown.currentCurve, shown.previousCurve })
                if (curve != null) foreach (var p in curve)
                    foreach (var raw in new[] { p.rawForward, p.rawTurn })
                    { double v = Value(raw); if (!double.IsNaN(v)) scale = Math.Max(scale, Math.Abs(v)); }
            return scale;
        }
        void DrawMotor(MeshGenerationContext context)
        {
            if (shown == null) return;
            DrawCurve(context, shown.previousCurve, 1, .3f, motorPlot.contentRect, true);
            if (currentFresh) DrawCurve(context, shown.currentCurve, 1, 1, motorPlot.contentRect, true);
        }
        void DrawCurve(MeshGenerationContext context, Point[] points, double scale, float alpha, Rect rect, bool motor)
        {
            if (points == null || points.Length > 32) return;
            var painter = context.painter2D;
            for (int axis = 0; axis < 2; axis++)
            {
                painter.strokeColor = axis == 0 ? new Color(.2f,.8f,1,alpha) : new Color(1,.65f,.2f,alpha);
                painter.lineWidth = 1.5f; bool started = false;
                foreach (var p in points)
                {
                    double x = Value(p.timeMs), y = Value(motor ? (axis == 0 ? p.motorForward : p.motorTurn)
                        : (axis == 0 ? p.rawForward : p.rawTurn));
                    if (double.IsNaN(x) || double.IsNaN(y)) { if (started) painter.Stroke(); started = false; continue; }
                    Vector2 pos = new Vector2((float)Math.Clamp(x / 200, 0, 1) * rect.width,
                        rect.height * (.5f - .45f * (float)Math.Clamp(y / scale, -1, 1)));
                    if (!started) { painter.BeginPath(); painter.MoveTo(pos); started = true; }
                    else painter.LineTo(pos);
                }
                if (started) painter.Stroke();
            }
        }
        public static double Value(string text) => double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var v)
            && !double.IsNaN(v) && !double.IsInfinity(v) ? v : double.NaN;
        static string Format(string text) => double.IsNaN(Value(text)) ? "unknown" : Value(text).ToString("0.###", CultureInfo.InvariantCulture);

        // JsonUtility otherwise converts JSON null numeric fields into 0. Preserve
        // only the known measurement fields as strings before parsing the DTO.
        static readonly Regex Numeric = new Regex("(?<!\\\\)\"(L|R|ageMs|sequence|brainSequence|currentSequence|brainTimeOffsetMs|timeMs|forward|turn|horizontalSpeed|forwardSpeed|yawRateDegPerSec|rawForward|rawTurn|motorForward|motorTurn|requestedRequestId|appliedRequestId|currentMeanMv|previousMeanMv|deltaMeanMv|directionalDeltaMv)\"\\s*:\\s*(null|-?[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?=\\s*[,}])", RegexOptions.CultureInvariant);
        public static Observation Parse(string json) => JsonUtility.FromJson<Observation>(Numeric.Replace(json, m =>
            "\"" + m.Groups[1].Value + "\":\"" + (m.Groups[2].Value == "null" ? "unknown" : m.Groups[2].Value) + "\""));
        [Serializable] public sealed class Observation
        {
            public int schemaVersion, controlEpoch, conversationGeneration;
            public bool fresh; public string ageMs, sequence, eventType, mode;
            public Identity identity; public Current current; public Body body; public Comparison comparison;
            public Aggregation selectedVncAggregation; public ReadoutProvenance readoutProvenance; public Calibration calibration;
            public Point[] currentCurve, previousCurve;
        }
        [Serializable] public sealed class Identity { public string sessionId, instanceId, backendId; }
        [Serializable] public sealed class Values { public string forward, turn; }
        [Serializable] public sealed class Sides { public string L, R; }
        [Serializable] public sealed class Populations { public Sides forward, turn; }
        [Serializable] public sealed class Current
        { public string requestedAction, observedAction, requestedRequestId, appliedRequestId; public bool stimulusApplied; public Values raw, filteredRaw, motor; public Populations populationDeltaMv; }
        [Serializable] public sealed class Body
        { public bool fresh, correlated; public string horizontalSpeed, forwardSpeed, yawRateDegPerSec, brainSequence, currentSequence, brainTimeOffsetMs; }
        [Serializable] public sealed class Comparison { public bool eligible, changed; public string reason; public string[] changedAxes; public ComparisonAxes axes; }
        [Serializable] public sealed class ComparisonAxes { public AxisComparison forward, turn; }
        [Serializable] public sealed class AxisComparison { public bool eligible, changed; public string currentMeanMv, previousMeanMv, deltaMeanMv, directionalDeltaMv; }
        [Serializable] public sealed class Aggregation { public string version, method, unit; }
        [Serializable] public sealed class Calibration { public bool valid; public string status, version, artifactSha256; }
        [Serializable] public sealed class ReadoutProvenance
        { public string DNg100_L_Hz, DNg100_R_Hz, DNa02_L_Hz, DNa02_R_Hz, DNp09_L_Hz, DNp09_R_Hz; }
        [Serializable] public sealed class Point { public string timeMs, rawForward, rawTurn, motorForward, motorTurn; }
    }
}
