using UnityEngine;

namespace FlyBrainVisualization
{
    /// <summary>Opt-in render-to-texture panel. Does not change the gameplay camera, input or physics.</summary>
    [DisallowMultipleComponent]
    public sealed class NeuralVisualizationPanel : MonoBehaviour
    {
        [SerializeField] private NeuralActivityObserver observer;
        [SerializeField] private NeuralPointCloud pointCloud;
        [SerializeField] private Camera brainCamera;
        [SerializeField] private Transform displayRoot;
        [SerializeField] private bool visible = true;
        [SerializeField, Range(.2f, .6f)] private float screenWidthFraction = .36f;
        [SerializeField, Range(256, 1536)] private int textureResolution = 768;
        [SerializeField] private bool allowOrbit = true;
        [Header("Anatomical framing (display crop, not cell classification)")]
        [SerializeField] private bool brainFocus = true;
        [SerializeField] private Vector3 brainFocusCenter = new Vector3(0, .66f, 0);
        [SerializeField, Min(.1f)] private float brainViewSize = .86f;
        [SerializeField, Min(.1f)] private float fullViewSize = 1.25f;

        private RenderTexture target;
        private GUIStyle titleStyle, smallStyle, valueStyle, stateStyle;
        private readonly float[] activityHistory = new float[100];
        private int historyCount, historyCursor;
        private string historyIdentity;
        private Vector2 angles = new Vector2(0, 12);
        private float zoom = 1.25f;
        private bool dragging;
        private bool embedded;
        public Texture DisplayTexture => target;
        public NeuralActivityObserver Observer => observer;
        public bool BrainFocus => brainFocus;
        public float DisplayGain { get => pointCloud == null ? 1f : pointCloud.DisplayGain; set { if (pointCloud != null) pointCloud.DisplayGain = value; } }
        public void SetEmbedded(bool value) { embedded = value; dragging = false; }
        public void Rotate(Vector2 delta)
        {
            if (!allowOrbit || displayRoot == null) return;
            angles.x = Mathf.Clamp(angles.x + delta.y * .35f, -65, 65); angles.y += delta.x * .35f;
            displayRoot.localRotation = Quaternion.Euler(angles.x, angles.y, 0);
            ApplyView();
        }
        public void Zoom(float delta)
        {
            zoom = Mathf.Clamp(zoom + delta * .035f, .45f, 2.5f);
            ApplyView();
        }
        public void SetBrainFocus(bool value)
        {
            brainFocus = value;
            zoom = Mathf.Max(.1f, value ? brainViewSize : fullViewSize);
            ApplyView();
        }
        private void ApplyView()
        {
            if (brainCamera == null || displayRoot == null) return;
            Vector3 center = displayRoot.TransformPoint(brainFocus ? brainFocusCenter : Vector3.zero);
            brainCamera.transform.position = center - brainCamera.transform.forward * 4f;
            brainCamera.orthographicSize = zoom;
            brainCamera.backgroundColor = new Color(.035f, .039f, .048f, 1);
        }
        private readonly Color ink = new Color(.035f, .039f, .048f, .98f);
        private readonly Color muted = new Color(.42f, .59f, .66f);
        private readonly Color cyan = new Color(.20f, .88f, .88f);
        private readonly Color gold = new Color(1f, .23f, .09f);

        public void Configure(NeuralActivityObserver data, NeuralPointCloud cloud, Camera camera, Transform content)
        {
            if (isActiveAndEnabled) OnDisable();
            observer = data; pointCloud = cloud; brainCamera = camera; displayRoot = content;
            if (isActiveAndEnabled) OnEnable();
        }
        public void SetVisible(bool value) { visible = value; if (brainCamera != null) brainCamera.enabled = value; }

        private void OnEnable()
        {
            if (observer != null) observer.FrameApplied += RecordFrame;
            if (brainCamera == null) return;
            int resolution = Mathf.Clamp(textureResolution, 256, 1536);
            target = new RenderTexture(resolution, resolution, 16, RenderTextureFormat.ARGB32)
            { name = "Neural Observatory", antiAliasing = 1 };
            target.Create();
            brainCamera.targetTexture = target;
            brainCamera.enabled = visible;
            SetBrainFocus(brainFocus);
        }

        private void RecordFrame()
        {
            if (historyIdentity != observer.SessionIdentity)
            { historyIdentity = observer.SessionIdentity; historyCount = historyCursor = 0; }
            activityHistory[historyCursor] = observer.WindowMs > 0 ? observer.SpikeCount * 1000f / observer.WindowMs : 0;
            historyCursor = (historyCursor + 1) % activityHistory.Length;
            historyCount = Mathf.Min(historyCount + 1, activityHistory.Length);
        }

        private void OnGUI()
        {
            if (embedded || !visible || observer == null) return;
            InitStyles();
            Color oldColor = GUI.color;
            int oldDepth = GUI.depth; GUI.depth = -20;
            float width = Mathf.Min(Screen.width - 24, Mathf.Max(280, Screen.width * screenWidthFraction));
            Rect panel = new Rect(Screen.width - width - 12, 12, width, Screen.height - 24);
            Fill(panel, ink);
            Fill(new Rect(panel.x, panel.y, 2, panel.height), new Color(.15f, .68f, .76f, .6f));
            float x = panel.x + 22, w = width - 44, y = panel.y + 19;
            GUI.Label(new Rect(x, y, w, 24), "NEURAL OBSERVATORY", titleStyle);
            GUI.Label(new Rect(x, y + 28, Mathf.Max(0, w - 100), 20), "MALE CNS / SOMATA", smallStyle);
            if (GUI.Button(new Rect(x + w - 96, y + 27, 96, 23), brainFocus ? "FULL CNS" : "BRAIN FOCUS")) SetBrainFocus(!brainFocus);
            float size = Mathf.Min(w, Mathf.Max(80, panel.height - 290));
            Rect brainRect = new Rect(x + (w - size) / 2, y + 60, size, size);
            if (target != null) GUI.DrawTexture(brainRect, target, ScaleMode.ScaleToFit, false);
            Orbit(brainRect);
            y = brainRect.yMax + 9;
            string age = observer.FrameAgeMs < 0 ? "—" : observer.FrameAgeMs.ToString("0") + " ms";
            stateStyle.normal.textColor = observer.IsFresh ? cyan : muted;
            GUI.Label(new Rect(x, y, w, 20), observer.Mode + "  ·  " + observer.State, stateStyle);
            GUI.Label(new Rect(x, y + 22, w, 18), "FRAME AGE  " + age + "     READY  " + observer.Ready.ToString().ToLowerInvariant(), smallStyle);
            y += 52;
            GUI.Label(new Rect(x, y, w * .5f, 25), observer.IsFresh && observer.WindowMs > 0 ? observer.ActiveCount.ToString("N0") : "—", valueStyle);
            GUI.Label(new Rect(x + w * .5f, y, w * .5f, 25), observer.IsFresh && observer.WindowMs > 0 ? observer.SpikeCount.ToString("N0") : "—", valueStyle);
            GUI.Label(new Rect(x, y + 28, w * .5f, 16), "ACTIVE SOMATA", smallStyle);
            GUI.Label(new Rect(x + w * .5f, y + 28, w * .5f, 16), "SPIKES / WINDOW", smallStyle);
            y += 57;
            DrawHistory(new Rect(x, y, w, 30));
            y += 38;
            GUI.Label(new Rect(x, y, w, 18), "SAMPLE  " + observer.ObservedCount.ToString("N0") + " / " + observer.PointCount.ToString("N0") + "   ·   SEQ  " + observer.Sequence + "   ·   SKIP  " + observer.DroppedFrames, smallStyle);
            y += 24;
            Fill(new Rect(x, y + 5, 5, 5), gold);
            GUI.Label(new Rect(x + 12, y, w - 12, 18), "RED: SPIKES  ·  WHITE: OBSERVED IDLE", smallStyle);
            y += 24;
            GUI.Label(new Rect(x, y, 65, 18), "GLOW", smallStyle);
            if (pointCloud != null) pointCloud.DisplayGain = GUI.HorizontalSlider(new Rect(x + 66, y + 5, Mathf.Max(50, w - 66), 16), pointCloud.DisplayGain, .1f, 3f);
            GUI.Label(new Rect(x, panel.yMax - 25, w, 18), "GRAY: UNOBSERVED  ·  WINDOW AFTERGLOW", smallStyle);
            GUI.depth = oldDepth; GUI.color = oldColor;
        }

        private void Orbit(Rect area)
        {
            if (!allowOrbit || displayRoot == null || brainCamera == null) return;
            var e = Event.current;
            if (e.type == EventType.MouseDown && e.button == 0 && area.Contains(e.mousePosition)) { dragging = true; e.Use(); }
            if (e.type == EventType.MouseUp && dragging) { dragging = false; e.Use(); }
            if (e.type == EventType.MouseDrag && dragging)
            {
                Rotate(e.delta); e.Use();
            }
            if (e.type == EventType.ScrollWheel && area.Contains(e.mousePosition))
            { Zoom(e.delta.y); e.Use(); }
        }

        private void DrawHistory(Rect rect)
        {
            Fill(new Rect(rect.x, rect.yMax, rect.width, 1), new Color(.15f, .26f, .32f));
            if (!observer.IsFresh || observer.WindowMs <= 0) return;
            float max = 1;
            for (int i = 0; i < historyCount; i++) max = Mathf.Max(max, activityHistory[i]);
            float bar = rect.width / activityHistory.Length;
            for (int i = 0; i < historyCount; i++)
            {
                int index = (historyCursor - historyCount + i + activityHistory.Length) % activityHistory.Length;
                float height = rect.height * activityHistory[index] / max;
                Fill(new Rect(rect.x + i * bar, rect.yMax - height, Mathf.Max(1, bar - 1), height), new Color(.3f, .73f, .75f, .7f));
            }
        }

        private void InitStyles()
        {
            if (titleStyle != null) return;
            titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 18, fontStyle = FontStyle.Bold };
            titleStyle.normal.textColor = new Color(.84f, .93f, .95f);
            smallStyle = new GUIStyle(GUI.skin.label) { fontSize = 10 }; smallStyle.normal.textColor = muted;
            valueStyle = new GUIStyle(titleStyle) { fontSize = 26 };
            stateStyle = new GUIStyle(smallStyle) { fontSize = 11 };
        }
        private static void Fill(Rect rect, Color color)
        { GUI.color = color; GUI.DrawTexture(rect, Texture2D.whiteTexture); GUI.color = Color.white; }

        private void OnDisable()
        {
            if (observer != null) observer.FrameApplied -= RecordFrame;
            if (brainCamera != null) { brainCamera.enabled = false; brainCamera.targetTexture = null; }
            if (target != null) { target.Release(); Destroy(target); target = null; }
            historyCount = historyCursor = 0; dragging = false;
        }
    }
}
