using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.PlayScreen
{
    /// <summary>
    /// Decorative, data-owned context cue for the play screen. It intentionally represents
    /// game state only; it makes no claim about the brain's internal state or feelings.
    /// </summary>
    public sealed class BrainContextHalo : VisualElement
    {
        public enum Context
        {
            Waiting,
            Calm,
            Danger,
            Goal,
            Ended
        }

        static readonly Color WaitingColor = new Color(.42f, .51f, .58f, .34f);
        static readonly Color CalmColor = new Color(.38f, .94f, .77f, 1f);
        static readonly Color DangerColor = new Color(1f, .40f, .34f, 1f);
        static readonly Color GoalColor = new Color(1f, .76f, .30f, 1f);
        static readonly Color EndedColor = new Color(.48f, .45f, .57f, .27f);

        Context current = Context.Waiting;
        float time;

        public BrainContextHalo()
        {
            pickingMode = PickingMode.Ignore;
            generateVisualContent += Draw;
        }

        /// <summary>Updates the game context and its unscaled display time on the owner's UI refresh.</summary>
        public void SetContext(Context value, float unscaledTime)
        {
            current = value;
            time = unscaledTime;
            MarkDirtyRepaint();
        }

        void Draw(MeshGenerationContext context)
        {
            Rect bounds = contentRect;
            if (bounds.width < 8f || bounds.height < 8f) return;

            Painter2D painter = context.painter2D;
            Vector2 center = bounds.center;
            float minSide = Mathf.Min(bounds.width, bounds.height);
            float outerX = Mathf.Max(2f, minSide * .49f);
            float outerY = outerX;
            float baseLineWidth = Mathf.Clamp(minSide * .012f, 1f, 3.5f);

            switch (current)
            {
                case Context.Calm:
                    DrawCalm(painter, center, outerX, outerY, baseLineWidth);
                    break;
                case Context.Danger:
                    DrawDanger(painter, center, outerX, outerY, baseLineWidth);
                    break;
                case Context.Goal:
                    DrawGoal(painter, center, outerX, outerY, baseLineWidth);
                    break;
                case Context.Ended:
                    DrawStatic(painter, center, outerX, outerY, baseLineWidth, EndedColor);
                    break;
                default:
                    DrawStatic(painter, center, outerX, outerY, baseLineWidth, WaitingColor);
                    break;
            }
        }

        void DrawCalm(Painter2D painter, Vector2 center, float outerX, float outerY, float lineWidth)
        {
            float breath = .5f + .5f * Mathf.Sin(time * 1.35f);
            Color color = CalmColor;
            color.a = .28f + breath * .32f;
            StrokeEllipse(painter, center, outerX * (.91f + breath * .025f), outerY * (.91f + breath * .025f), lineWidth, color);
            color.a *= .58f;
            StrokeEllipse(painter, center, outerX * (.79f - breath * .012f), outerY * (.79f - breath * .012f), lineWidth * .72f, color);
        }

        void DrawDanger(Painter2D painter, Vector2 center, float outerX, float outerY, float lineWidth)
        {
            float pulse = .5f + .5f * Mathf.Sin(time * 6.8f);
            Color color = DangerColor;
            color.a = .35f + pulse * .48f;
            float scale = .89f + pulse * .055f;
            StrokeEllipse(painter, center, outerX * scale, outerY * scale, lineWidth * (1.05f + pulse * .45f), color);
            color.a *= .48f;
            StrokeEllipse(painter, center, outerX * (.76f + pulse * .04f), outerY * (.76f + pulse * .04f), lineWidth * .72f, color);
        }

        void DrawGoal(Painter2D painter, Vector2 center, float outerX, float outerY, float lineWidth)
        {
            // Time-offset waves create a slow repeating outward progression without persistent scheduling.
            for (int i = 0; i < 3; i++)
            {
                float wave = Mathf.Repeat(time * .30f + i / 3f, 1f);
                Color color = GoalColor;
                color.a = (1f - wave) * .54f;
                float scale = .60f + wave * .34f;
                StrokeEllipse(painter, center, outerX * scale, outerY * scale, lineWidth * (.78f + (1f - wave) * .25f), color);
            }
        }

        static void DrawStatic(Painter2D painter, Vector2 center, float outerX, float outerY, float lineWidth, Color color)
        {
            StrokeEllipse(painter, center, outerX * .90f, outerY * .90f, lineWidth, color);
            color.a *= .55f;
            StrokeEllipse(painter, center, outerX * .78f, outerY * .78f, lineWidth * .7f, color);
        }

        static void StrokeEllipse(Painter2D painter, Vector2 center, float radiusX, float radiusY, float lineWidth, Color color)
        {
            const int Sides = 64;
            painter.strokeColor = color;
            painter.lineWidth = lineWidth;
            painter.BeginPath();
            for (int i = 0; i <= Sides; i++)
            {
                float angle = i * Mathf.PI * 2f / Sides;
                Vector2 point = center + new Vector2(Mathf.Cos(angle) * radiusX, Mathf.Sin(angle) * radiusY);
                if (i == 0) painter.MoveTo(point); else painter.LineTo(point);
            }
            painter.ClosePath();
            painter.Stroke();
        }
    }
}
