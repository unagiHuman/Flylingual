using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.PlayScreen
{
    /// <summary>Small vector illustration. Its expression is a labelled UI metaphor, never a neural inference.</summary>
    public sealed class FlyPortraitElement : VisualElement
    {
        string expression = "待機";
        float activity;
        float phase;

        public FlyPortraitElement()
        {
            generateVisualContent += Draw;
            pickingMode = PickingMode.Ignore;
        }

        public void SetPresentation(string nextExpression, float nextActivity, float time)
        {
            expression = string.IsNullOrEmpty(nextExpression) ? "待機" : nextExpression;
            activity = Mathf.Clamp01(nextActivity);
            phase = time;
            MarkDirtyRepaint();
        }

        void Draw(MeshGenerationContext context)
        {
            Rect r = contentRect;
            if (r.width < 8 || r.height < 8) return;
            var p = context.painter2D;
            Vector2 c = r.center + new Vector2(0, Mathf.Sin(phase * 1.7f) * Mathf.Min(3f, r.height * .025f));
            float u = Mathf.Min(r.width, r.height) / 190f;
            Color ink = new Color(.08f, .13f, .19f);
            Color amber = new Color(1f, .67f, .25f);
            Color wing = new Color(.50f, .90f, .83f, .35f + activity * .18f);
            Color cream = new Color(1f, .96f, .83f);

            p.lineWidth = Mathf.Max(1.5f, 3f * u);
            p.strokeColor = ink;
            p.fillColor = wing;
            Ellipse(p, c + new Vector2(-42, -18) * u, 38 * u, 22 * u); p.Fill(); p.Stroke();
            Ellipse(p, c + new Vector2(42, -18) * u, 38 * u, 22 * u); p.Fill(); p.Stroke();
            p.fillColor = amber;
            Ellipse(p, c + new Vector2(0, 12) * u, 45 * u, 56 * u); p.Fill(); p.Stroke();
            p.fillColor = new Color(.18f, .23f, .30f);
            Ellipse(p, c + new Vector2(0, -40) * u, 51 * u, 39 * u); p.Fill(); p.Stroke();
            p.fillColor = cream;
            Ellipse(p, c + new Vector2(-21, -44) * u, 16 * u, 18 * u); p.Fill(); p.Stroke();
            Ellipse(p, c + new Vector2(21, -44) * u, 16 * u, 18 * u); p.Fill(); p.Stroke();
            p.fillColor = ink;
            Ellipse(p, c + new Vector2(-18, -42) * u, 6 * u, 8 * u); p.Fill();
            Ellipse(p, c + new Vector2(18, -42) * u, 6 * u, 8 * u); p.Fill();

            // Antennae and six legs keep the silhouette recognisably insect-like at small sizes.
            p.strokeColor = ink;
            for (int side = -1; side <= 1; side += 2)
            {
                Vector2 antenna = c + new Vector2(side * 24, -69) * u;
                p.BeginPath(); p.MoveTo(c + new Vector2(side * 15, -65) * u); p.LineTo(antenna); p.LineTo(antenna + new Vector2(side * 7, -7) * u); p.Stroke();
            }

            // A minimal factual state-dependent mouth; it does not encode an emotion claim.
            p.fillColor = ink;
            float mouth = expression == "発話中" ? 11f : expression == "聞いています" ? 4f : 7f;
            Ellipse(p, c + new Vector2(0, -19) * u, 11 * u, mouth * u); p.Fill();
            p.strokeColor = ink;
            for (int side = -1; side <= 1; side += 2)
            {
                for (int pair = 0; pair < 3; pair++)
                {
                    float y = 28 + pair * 15;
                    Vector2 start = c + new Vector2(side * 27, y) * u;
                    p.BeginPath(); p.MoveTo(start); p.LineTo(start + new Vector2(side * (21 + pair * 3), 15 + pair * 5) * u); p.Stroke();
                }
            }
            p.fillColor = new Color(.41f, .95f, .79f, .9f);
            float dot = (5f + activity * 7f) * u;
            Ellipse(p, c + new Vector2(0, 30) * u, dot, dot); p.Fill();
        }

        static void Ellipse(Painter2D p, Vector2 center, float radiusX, float radiusY)
        {
            const int sides = 20;
            p.BeginPath();
            for (int i = 0; i <= sides; i++)
            {
                float angle = i * Mathf.PI * 2f / sides;
                Vector2 point = center + new Vector2(Mathf.Cos(angle) * radiusX, Mathf.Sin(angle) * radiusY);
                if (i == 0) p.MoveTo(point); else p.LineTo(point);
            }
            p.ClosePath();
        }
    }
}
