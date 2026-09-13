using Flylingual.PlayScreen;
using UnityEngine;
using UnityEngine.UIElements;

namespace Flylingual.BlindSugarRun
{
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunMinimapView : MonoBehaviour
    {
        BlindSugarRunExplorationMap map;
        Camera gameCamera;
        VisualElement root, canvas;
        float nextRefresh;
        public VisualElement Root => root;
        public bool Visible => root != null && root.resolvedStyle.display != DisplayStyle.None;

        public void Configure(BlindSugarRunExplorationMap exploration, Camera camera)
        { map = exploration; gameCamera = camera; TryAttach(); }

        void Update()
        {
            if (Time.unscaledTime < nextRefresh || map == null) return;
            nextRefresh = Time.unscaledTime + .2f;
            if (root == null) TryAttach();
            if (root == null) return;
            bool ending = map.stage != null && (map.stage.State == BlindSugarRunSession.StageState.Goal || map.stage.State == BlindSugarRunSession.StageState.Reveal);
            root.style.display = ending ? DisplayStyle.None : DisplayStyle.Flex;
            canvas.MarkDirtyRepaint();
        }

        void TryAttach()
        {
            if (root != null || map == null || gameCamera == null) return;
            var view = FindAnyObjectByType<PlayScreenView>();
            if (view == null || !view.IsBuilt) return;
            var document = view.GetComponent<UIDocument>();
            if (document == null) return;
            var image = document.rootVisualElement.Query<Image>().ToList().Find(item => item.image == gameCamera.targetTexture);
            if (image?.parent == null) return;
            root = new VisualElement { name = "blind-sugar-exploration-map", pickingMode = PickingMode.Ignore };
            root.style.position = Position.Absolute; root.style.top = 42; root.style.right = 12;
            root.style.width = 210; root.style.height = 250;
            root.style.paddingLeft = root.style.paddingRight = 8; root.style.paddingTop = root.style.paddingBottom = 6;
            root.style.backgroundColor = new Color(.025f, .055f, .08f, .96f);
            root.style.borderTopLeftRadius = root.style.borderTopRightRadius = root.style.borderBottomLeftRadius = root.style.borderBottomRightRadius = 8;
            var heading = new VisualElement { pickingMode = PickingMode.Ignore }; heading.style.flexDirection = FlexDirection.Row;
            var title = Text("探索マップ", new Color(.78f, 1f, .9f), 13); title.style.flexGrow = 1; heading.Add(title);
            heading.Add(Text("N ↑", Color.white, 11)); root.Add(heading);
            canvas = new MapCanvas(map); canvas.style.flexGrow = 1; canvas.style.marginTop = 4; canvas.style.overflow = Overflow.Hidden; root.Add(canvas);
            var legend = new VisualElement { pickingMode = PickingMode.Ignore }; legend.style.flexDirection = FlexDirection.Row;
            legend.style.justifyContent = Justify.SpaceBetween; legend.style.marginTop = 4;
            legend.Add(Text("■ 探索済", MapCanvas.Ground, 10)); legend.Add(Text("■ 足跡", MapCanvas.Visited, 10)); legend.Add(Text("━ 崖", MapCanvas.Cliff, 10)); root.Add(legend);
            image.parent.Add(root);
        }

        static Label Text(string text, Color color, int size)
        { var label = new Label(text) { pickingMode = PickingMode.Ignore }; label.style.color = color; label.style.fontSize = size; return label; }

        void OnDestroy() { root?.RemoveFromHierarchy(); root = null; }

        sealed class MapCanvas : VisualElement
        {
            readonly BlindSugarRunExplorationMap map;
            const float Range = 20f;
            public static readonly Color Ground = new Color(.62f, .84f, .72f), Visited = new Color(1f, .68f, .2f), Cliff = new Color(1f, .28f, .22f);
            static readonly Vector2Int[] Directions = { Vector2Int.right, Vector2Int.up, Vector2Int.left, Vector2Int.down };
            public MapCanvas(BlindSugarRunExplorationMap map)
            { this.map = map; pickingMode = PickingMode.Ignore; generateVisualContent += Paint; }

            void Paint(MeshGenerationContext context)
            {
                var painter = context.painter2D;
                float side = Mathf.Min(contentRect.width, contentRect.height);
                if (side < 1) return;
                Vector2 center = contentRect.center;
                Rect square = new Rect(center - Vector2.one * side * .5f, Vector2.one * side);
                painter.fillColor = new Color(.012f, .022f, .032f); Box(painter, square);
                Vector3 player = map.PlayerPosition;
                const float cellSize = BlindSugarRunExplorationMap.CellSize;
                int minX = Mathf.FloorToInt((player.x - Range * .5f) / cellSize), maxX = Mathf.CeilToInt((player.x + Range * .5f) / cellSize);
                int minZ = Mathf.FloorToInt((player.z - Range * .5f) / cellSize), maxZ = Mathf.CeilToInt((player.z + Range * .5f) / cellSize);
                float pixels = side * cellSize / Range;
                for (int z = minZ; z <= maxZ; z++)
                for (int x = minX; x <= maxX; x++)
                {
                    var key = new Vector2Int(x,z);
                    if (!map.Cells.TryGetValue(key, out var cell) || !cell.ground) continue;
                    Vector2 topLeft = center + new Vector2(x * cellSize - player.x, player.z - (z + 1) * cellSize) * (side / Range);
                    var rect = new Rect(topLeft, new Vector2(pixels,pixels));
                    if (!square.Overlaps(rect)) continue;
                    painter.fillColor = cell.visited ? Visited : Ground; Box(painter, rect);
                    for (int edge = 0; edge < 4; edge++)
                    {
                        // Unknown frontier stays dark; only two observed samples can establish a cliff.
                        if (!map.Cells.TryGetValue(key + Directions[edge], out var neighbour) ||
                            (neighbour.ground && Mathf.Abs(cell.height - neighbour.height) <= .5f)) continue;
                        Vector2 a, b;
                        if (edge == 0) { a = new Vector2(rect.xMax,rect.yMin); b = new Vector2(rect.xMax,rect.yMax); }
                        else if (edge == 1) { a = rect.min; b = new Vector2(rect.xMax,rect.yMin); }
                        else if (edge == 2) { a = rect.min; b = new Vector2(rect.xMin,rect.yMax); }
                        else { a = new Vector2(rect.xMin,rect.yMax); b = rect.max; }
                        painter.strokeColor = Cliff; painter.lineWidth = 1.6f; painter.BeginPath(); painter.MoveTo(a); painter.LineTo(b); painter.Stroke();
                    }
                }
                Vector3 forward = map.PlayerForward;
                Vector2 direction = new Vector2(forward.x,-forward.z).normalized;
                if (direction.sqrMagnitude < .01f) direction = Vector2.up * -1;
                Vector2 right = new Vector2(-direction.y,direction.x);
                painter.fillColor = new Color(.35f,1f,.9f); painter.strokeColor = new Color(.015f,.06f,.08f); painter.lineWidth = 1.5f;
                painter.BeginPath(); painter.MoveTo(center + direction * 7); painter.LineTo(center - direction * 4 + right * 4);
                painter.LineTo(center - direction * 4 - right * 4); painter.ClosePath(); painter.Fill(); painter.Stroke();
            }

            static void Box(Painter2D painter, Rect rect)
            {
                painter.BeginPath(); painter.MoveTo(rect.min); painter.LineTo(new Vector2(rect.xMax,rect.yMin));
                painter.LineTo(rect.max); painter.LineTo(new Vector2(rect.xMin,rect.yMax)); painter.ClosePath(); painter.Fill();
            }
        }
    }
}
