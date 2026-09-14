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
        readonly VisualElement plot = new VisualElement();
        readonly VisualElement motorPlot = new VisualElement();
        Observation shown;
        bool currentFresh;
        public NeuralResponsePanel()
        {
            style.flexShrink = 0; style.paddingTop = 5;
            readings.style.fontSize = 11; readings.style.whiteSpace = WhiteSpace.Normal;
            legend.style.fontSize = 10; legend.style.whiteSpace = WhiteSpace.Normal;
            plot.style.height = 42; plot.generateVisualContent += Draw;
            motorPlot.style.height = 30; motorPlot.generateVisualContent += DrawMotor;
            Add(readings); Add(plot); Add(motorPlot); Add(legend);
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
                "\nraw mV  F " + Format(now?.raw?.forward) + " / T " + Format(now?.raw?.turn) +
                "  motor " + Format(now?.motor?.forward) + " / " + Format(now?.motor?.turn) +
                "\npop ΔmV F L/R " + Format(now?.populationDeltaMv?.forward?.L) + "/" + Format(now?.populationDeltaMv?.forward?.R) +
                "  T L/R " + Format(now?.populationDeltaMv?.turn?.L) + "/" + Format(now?.populationDeltaMv?.turn?.R) +
                GameLanguage.Text("\n身体 m/s ", "\nBody m/s ") + Format(body?.horizontalSpeed) + GameLanguage.Text("  前方 ", "  Forward ") + Format(body?.forwardSpeed) +
                "  yaw °/s " + Format(body?.yawRateDegPerSec) +
                GameLanguage.Text("\n身体対応seq ", "\nBody matched seq ") + (body?.brainSequence ?? unknown) +
                " / " + (shown?.sequence ?? unknown) + GameLanguage.Text(" (現行) Δ脳内 ", " (current) Δbrain ") +
                Format(body?.brainTimeOffsetMs) + "ms" +
                "\n" + (shown?.identity?.backendId ?? unknown) + " " + (shown?.mode ?? unknown) + " | age " +
                (double.IsNaN(age) || double.IsInfinity(age) ? unknown : age.ToString("0", CultureInfo.InvariantCulture) + "ms") +
                (currentFresh ? "" : GameLanguage.Text(" | 現在値unknown", " | Current unknown"));
            legend.text = GameLanguage.Text("選択VNC raw: 前進=青 / 旋回=橙。薄線=比較履歴。身体確認・感情の証明ではない。",
                "Selected VNC raw: forward blue / turn orange; faded = previous. Not evidence of body motion or feelings.");
            legend.text += GameLanguage.Text(" yawのmotor符号対応は未校正。", " Yaw-to-motor sign uncalibrated.");
            legend.text += GameLanguage.Text(" 上:raw可変mV軸 / 下:motor±1固定。除外した適用確認窓の終端を0として200脳内ms。原因未確定。",
                " Top: raw auto mV; bottom: motor fixed ±1. X: 200 brain ms from the end of the excluded application window. Cause unresolved.");
            if (shown?.comparison != null && !shown.comparison.eligible)
                legend.text += GameLanguage.Text(" 比較: ", " Comparison: ") + (shown.comparison.reason ?? unknown);
            if (shown != null) legend.text += " raw ±" + RawScale().ToString("0.###", CultureInfo.InvariantCulture) + "mV";
            plot.MarkDirtyRepaint(); motorPlot.MarkDirtyRepaint();
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
        static readonly Regex Numeric = new Regex("(?<!\\\\)\"(L|R|ageMs|sequence|brainSequence|currentSequence|brainTimeOffsetMs|timeMs|forward|turn|horizontalSpeed|forwardSpeed|yawRateDegPerSec|rawForward|rawTurn|motorForward|motorTurn|requestedRequestId|appliedRequestId)\"\\s*:\\s*(null|-?[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?=\\s*[,}])", RegexOptions.CultureInvariant);
        public static Observation Parse(string json) => JsonUtility.FromJson<Observation>(Numeric.Replace(json, m =>
            "\"" + m.Groups[1].Value + "\":\"" + (m.Groups[2].Value == "null" ? "unknown" : m.Groups[2].Value) + "\""));
        [Serializable] public sealed class Observation
        {
            public int schemaVersion, controlEpoch, conversationGeneration;
            public bool fresh; public string ageMs, sequence, eventType, mode;
            public Identity identity; public Current current; public Body body; public Comparison comparison;
            public Point[] currentCurve, previousCurve;
        }
        [Serializable] public sealed class Identity { public string sessionId, instanceId, backendId; }
        [Serializable] public sealed class Values { public string forward, turn; }
        [Serializable] public sealed class Sides { public string L, R; }
        [Serializable] public sealed class Populations { public Sides forward, turn; }
        [Serializable] public sealed class Current
        { public string requestedAction, observedAction, requestedRequestId, appliedRequestId; public bool stimulusApplied; public Values raw, motor; public Populations populationDeltaMv; }
        [Serializable] public sealed class Body
        { public bool fresh, correlated; public string horizontalSpeed, forwardSpeed, yawRateDegPerSec, brainSequence, currentSequence, brainTimeOffsetMs; }
        [Serializable] public sealed class Comparison { public bool eligible; public string reason; }
        [Serializable] public sealed class Point { public string timeMs, rawForward, rawTurn, motorForward, motorTurn; }
    }
}
