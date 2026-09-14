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
            currentFresh = IsFresh(shown, receivedAge);
            var now = currentFresh ? shown.current : null;
            string unknown = "unknown";
            string applied = now != null && now.stimulusApplied ? now.appliedRequestId ?? unknown : unknown;
            if (now != null && !now.stimulusApplied && !string.IsNullOrEmpty(now.requestedRequestId)
                && now.requestedRequestId != unknown) applied = GameLanguage.Text("受付済・適用待ち", "Accepted / pending application");
            var body = IsBodyFresh(shown, receivedAge) ? shown.body : null;
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
            detailReadings.text += "\n" + CalibrationText(currentFresh ? shown?.calibration : null);
            detailReadings.text += "\n" + ProvenanceText("DNg100 L", currentFresh ? shown?.readoutProvenance?.DNg100_L_Hz : null);
            detailReadings.text += "\n" + ProvenanceText("DNg100 R", currentFresh ? shown?.readoutProvenance?.DNg100_R_Hz : null);
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
                bool ready = calibration != null && calibration.artifactVerified && calibration.identityMatched &&
                    (axis == "forward" ? calibration.classificationReady?.changeForward == true : calibration.classificationReady?.changeTurn == true);
                if (ready && value.changed)
                    result += GameLanguage.Text("（校正閾値超）", " (above calibrated threshold)");
                else if (!ready) result += GameLanguage.Text("（数値のみ）", " (numeric only)");
            }
            if (calibration == null || !calibration.artifactVerified || !calibration.identityMatched ||
                (calibration.classificationReady?.changeForward != true && calibration.classificationReady?.changeTurn != true))
                result += GameLanguage.Text("\n未校正: 数値のみ。強弱・有意な変化は判定しません。",
                    "\nUncalibrated: numbers only; no strength or significant-change classification.");
            return result;
        }
        public static bool IsFresh(Observation observation, double elapsedSinceReceiptMs)
        {
            if (observation == null || !observation.fresh) return false;
            double sourceAge = Value(observation.ageMs);
            double limit = !observation.staleAfterMsPresent && observation.staleAfterMs == null ? 750 : Value(observation.staleAfterMs);
            return !double.IsNaN(sourceAge) && sourceAge >= 0 && !double.IsNaN(limit) && limit > 0 && limit <= 750
                && !double.IsNaN(elapsedSinceReceiptMs) && !double.IsInfinity(elapsedSinceReceiptMs) && elapsedSinceReceiptMs >= 0
                && sourceAge + elapsedSinceReceiptMs <= limit;
        }
        public static bool IsBodyFresh(Observation observation, double elapsedSinceReceiptMs)
        {
            if (!IsFresh(observation, elapsedSinceReceiptMs) || observation.body == null ||
                !observation.body.fresh || !observation.body.correlated) return false;
            double age = Value(observation.body.ageMs);
            double limit = !observation.staleAfterMsPresent && observation.staleAfterMs == null ? 750 : Value(observation.staleAfterMs);
            return !double.IsNaN(age) && age >= 0 && age + elapsedSinceReceiptMs <= limit;
        }
        public static string CalibrationText(Calibration calibration)
        {
            string result = GameLanguage.Text("Artifact検証: ", "Artifact verified: ") + (calibration?.artifactVerified == true) +
                GameLanguage.Text(" / Brain identity一致: ", " / Brain identity matched: ") + (calibration?.identityMatched == true);
            bool verified = calibration?.artifactVerified == true && calibration.identityMatched;
            var ready = calibration?.classificationReady;
            bool[] flags = { verified && ready?.responseForward == true, verified && ready?.responseTurn == true,
                verified && ready?.changeForward == true, verified && ready?.changeTurn == true, verified && ready?.stopResidual == true };
            string[] names = { "Response F", "Response T", "Change F", "Change T", "STOP residual" };
            int count = 0;
            for (int i = 0; i < flags.Length; i++)
            {
                if (flags[i]) count++;
                result += "\n" + names[i] + ": " + (flags[i] ? GameLanguage.Text("判定可能", "ready") : GameLanguage.Text("未校正・数値のみ", "uncalibrated; numeric only"));
            }
            if (count > 0 && count < flags.Length) result += GameLanguage.Text("\n一部校正済み。", "\nPartially calibrated.");
            return result;
        }
        public static string ProvenanceText(string label, ReadoutOrigin origin)
        {
            if (origin == null || origin.kind != "neuron_readout" || origin.configuredStimulusGroups == null)
                return label + ": unknown";
            string groups = origin.configuredStimulusGroups.Length == 0 ? GameLanguage.Text("なし", "none") : string.Join(",", origin.configuredStimulusGroups);
            return label + " (body ID " + origin.bodyId + ")" + GameLanguage.Text(" 設定上の刺激group: ", " configured stimulus groups: ") + groups +
                GameLanguage.Text(" / 現在Actionの刺激候補: ", " / current Action stimulus candidate: ") + origin.eligibleForDirectStimulation +
                GameLanguage.Text("。この窓での刺激イベント発生は未確認。", ". Stimulation events in this window are unverified.");
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
        static readonly Regex Numeric = new Regex("(?<!\\\\)\"(L|R|ageMs|staleAfterMs|sequence|brainSequence|currentSequence|brainTimeOffsetMs|timeMs|forward|turn|horizontalSpeed|forwardSpeed|yawRateDegPerSec|rawForward|rawTurn|motorForward|motorTurn|requestedRequestId|appliedRequestId|currentMeanMv|previousMeanMv|deltaMeanMv|directionalDeltaMv)\"\\s*:\\s*(null|-?[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?=\\s*[,}])", RegexOptions.CultureInvariant);
        public static Observation Parse(string json)
        {
            var observation = JsonUtility.FromJson<Observation>(Numeric.Replace(json, m =>
                "\"" + m.Groups[1].Value + "\":\"" + (m.Groups[2].Value == "null" ? "unknown" : m.Groups[2].Value) + "\""));
            if (observation != null) observation.staleAfterMsPresent = Regex.IsMatch(json, "\"staleAfterMs\"\\s*:");
            return observation;
        }
        [Serializable] public sealed class Observation
        {
            public int schemaVersion, controlEpoch, conversationGeneration;
            public bool fresh; public string ageMs, staleAfterMs, sequence, eventType, mode;
            [NonSerialized] public bool staleAfterMsPresent;
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
        { public bool fresh, correlated; public string ageMs, horizontalSpeed, forwardSpeed, yawRateDegPerSec, brainSequence, currentSequence, brainTimeOffsetMs; }
        [Serializable] public sealed class Comparison { public bool eligible, changed; public string reason; public string[] changedAxes; public ComparisonAxes axes; }
        [Serializable] public sealed class ComparisonAxes { public AxisComparison forward, turn; }
        [Serializable] public sealed class AxisComparison { public bool eligible, changed; public string currentMeanMv, previousMeanMv, deltaMeanMv, directionalDeltaMv; }
        [Serializable] public sealed class Aggregation { public string version, method, unit; }
        [Serializable] public sealed class Calibration { public bool valid, artifactVerified, identityMatched; public string status, version, artifactSha256; public ClassificationReady classificationReady; }
        [Serializable] public sealed class ClassificationReady { public bool responseForward, responseTurn, changeForward, changeTurn, stopResidual; }
        [Serializable] public sealed class ReadoutProvenance
        { public ReadoutOrigin DNg100_L_Hz, DNg100_R_Hz, DNa02_L_Hz, DNa02_R_Hz, DNp09_L_Hz, DNp09_R_Hz, DNp09_Hz, DNa02Difference_Hz, forward_raw, turn_raw; }
        [Serializable] public sealed class ReadoutOrigin { public string kind; public long bodyId; public string[] configuredStimulusGroups, derivedFrom; public bool eligibleForDirectStimulation; }
        [Serializable] public sealed class Point { public string timeMs, rawForward, rawTurn, motorForward, motorTurn; }
    }
}
