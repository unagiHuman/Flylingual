using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace FlyBrainVisualization
{
    /// <summary>
    /// Batched, observational rendering of neurons from a static atlas.
    /// Activity is an aggregate over the supplied window, not spike timing.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class NeuralPointCloud : MonoBehaviour
    {
        public const int MaxPointCount = 65536;

        private const int PointsPerChunk = 12000;
        private const string ShaderName = "FlyBrain/Neural Point Cloud";

        [Header("Material")]
        [SerializeField] private Material renderMaterial;
        [SerializeField, Min(0.001f)] private float pointSize = 0.012f;
        [SerializeField, Range(0f, 1f)] private float restingBrightness = 0.16f;
        [SerializeField, Min(0.01f)] private float spikeAfterglowSeconds = 0.18f;
        [SerializeField, Min(1f)] private float rateForFullGlowHz = 45f;
        [SerializeField, Min(0.01f)] private float membraneScaleMv = 2f;
        [SerializeField, Range(0f, 4f)] private float displayGain = 1f;
        [SerializeField] private bool inheritLayer = true;

        private readonly List<Chunk> chunks = new List<Chunk>();
        private Vector3[] pointPositions;
        private Material runtimeMaterial;
        private bool materialDirty = true;

        /// <summary>Multiplies measured firing-rate intensity before the shader clamps it.</summary>
        public float DisplayGain
        {
            get => displayGain;
            set
            {
                displayGain = Mathf.Clamp(value, 0f, 4f);
                materialDirty = true;
            }
        }

        /// <summary>
        /// Replaces the source material. Assign a project material using this component's shader
        /// so the shader remains included in player builds.
        /// </summary>
        public void SetMaterial(Material material)
        {
            if (renderMaterial == material && runtimeMaterial != null)
                return;

            Material previous = runtimeMaterial;
            renderMaterial = material;
            runtimeMaterial = null;
            EnsureMaterial();
            for (int i = 0; i < chunks.Count; ++i)
                chunks[i].SetMaterial(runtimeMaterial);
            if (previous != null)
                DestroyOwnedObject(previous);
            materialDirty = true;
            ApplyMaterialProperties();
        }

        /// <summary>Sets static local-space atlas positions. Rebuilds only when the atlas changes.</summary>
        public void SetPoints(Vector3[] positions)
        {
            if (positions != null && positions.Length > MaxPointCount)
                throw new ArgumentOutOfRangeException(nameof(positions), $"A point cloud supports at most {MaxPointCount} atlas positions.");
            if (positions != null)
            {
                for (int i = 0; i < positions.Length; ++i)
                {
                    if (!IsFinite(positions[i]))
                        throw new ArgumentException($"Atlas position {i} is not finite.", nameof(positions));
                }
            }
            ClearChunks();
            pointPositions = positions == null || positions.Length == 0 ? null : (Vector3[])positions.Clone();
            if (isActiveAndEnabled && pointPositions != null)
                BuildChunks();
        }

        /// <summary>
        /// Sets one observational aggregate frame. spikeCounts and deltaMv describe the given window,
        /// not individual spike times. Only observed points receive membrane or firing highlights.
        /// </summary>
        public void SetActivity(float[] spikeCounts, float[] deltaMv, bool[] observed, float windowMs)
        {
            if (pointPositions == null)
                return;

            if (spikeCounts != null && spikeCounts.Length != pointPositions.Length)
                throw new ArgumentException("spikeCounts must match the point count.", nameof(spikeCounts));
            if (deltaMv != null && deltaMv.Length != pointPositions.Length)
                throw new ArgumentException("deltaMv must match the point count.", nameof(deltaMv));
            if (observed == null || observed.Length != pointPositions.Length)
                throw new ArgumentException("observed must match the point count.", nameof(observed));

            EnsureBuilt();
            float inverseWindowSeconds = 1000f / Mathf.Max(0.001f, windowMs);
            float receiptTime = Time.unscaledTime;
            int globalIndex = 0;
            for (int chunkIndex = 0; chunkIndex < chunks.Count; ++chunkIndex)
            {
                Chunk chunk = chunks[chunkIndex];
                for (int pointIndex = 0; pointIndex < chunk.pointCount; ++pointIndex, ++globalIndex)
                {
                    bool isObserved = observed[globalIndex];
                    float count = spikeCounts == null || !IsFinite(spikeCounts[globalIndex])
                        ? 0f
                        : Mathf.Max(0f, spikeCounts[globalIndex]);
                    float normalizedRate = Mathf.Clamp01(count * inverseWindowSeconds / rateForFullGlowHz);
                    float membrane = 0.5f;
                    bool hasMembrane = false;
                    if (isObserved && deltaMv != null && IsFinite(deltaMv[globalIndex]))
                    {
                        membrane = Mathf.Clamp(deltaMv[globalIndex] / membraneScaleMv, -1f, 1f) * 0.5f + 0.5f;
                        hasMembrane = true;
                    }

                    // Color is repeated over a point's four billboard vertices. Time only advances
                    // for a measured nonzero aggregate; zeros do not fabricate visual firing.
                    Color packed = new Color(isObserved ? normalizedRate : 0f, membrane, isObserved ? 1f : 0f, hasMembrane ? 1f : 0f);
                    float spikeTime = isObserved && normalizedRate > 0f ? receiptTime : -10000f;
                    // A fresh observed zero is still a valid aggregate. It updates membrane state,
                    // but lets a prior measured firing aggregate decay for its remaining afterglow.
                    chunk.SetPoint(pointIndex, packed, spikeTime, isObserved && normalizedRate <= 0f);
                }
                chunk.UploadActivity();
            }
        }

        /// <summary>Immediately removes all measured highlighting, including afterglow.</summary>
        public void ClearActivity()
        {
            for (int i = 0; i < chunks.Count; ++i)
            {
                chunks[i].ClearActivity();
                chunks[i].UploadActivity();
            }
        }

        private void OnEnable()
        {
            if (pointPositions != null && chunks.Count == 0)
                BuildChunks();
        }

        private void OnDisable()
        {
            // A hidden then re-enabled display must not replay an old aggregate frame.
            ClearActivity();
        }

        private void OnDestroy()
        {
            ClearChunks();
            if (runtimeMaterial != null)
                DestroyOwnedObject(runtimeMaterial);
            runtimeMaterial = null;
        }

        private void LateUpdate()
        {
            if (materialDirty)
                ApplyMaterialProperties();
            if (runtimeMaterial != null)
                runtimeMaterial.SetFloat("_DisplayTime", Time.unscaledTime);
        }

        private void OnValidate()
        {
            pointSize = Mathf.Max(0.001f, pointSize);
            spikeAfterglowSeconds = Mathf.Max(0.01f, spikeAfterglowSeconds);
            rateForFullGlowHz = Mathf.Max(1f, rateForFullGlowHz);
            membraneScaleMv = Mathf.Max(0.01f, membraneScaleMv);
            displayGain = Mathf.Clamp(displayGain, 0f, 4f);
            materialDirty = true;
            UpdateChunkBounds();
        }

        private void EnsureBuilt()
        {
            if (chunks.Count == 0 && isActiveAndEnabled)
                BuildChunks();
        }

        private void BuildChunks()
        {
            if (pointPositions == null || pointPositions.Length == 0 || chunks.Count > 0)
                return;

            EnsureMaterial();
            for (int start = 0; start < pointPositions.Length; start += PointsPerChunk)
            {
                int count = Mathf.Min(PointsPerChunk, pointPositions.Length - start);
                GameObject child = new GameObject($"NeuralPointChunk_{chunks.Count:D2}");
                child.transform.SetParent(transform, false);
                if (inheritLayer)
                    child.layer = gameObject.layer;

                Mesh mesh = CreateChunkMesh(start, count);
                MeshFilter filter = child.AddComponent<MeshFilter>();
                MeshRenderer renderer = child.AddComponent<MeshRenderer>();
                filter.sharedMesh = mesh;
                renderer.sharedMaterial = runtimeMaterial;
                renderer.shadowCastingMode = ShadowCastingMode.Off;
                renderer.receiveShadows = false;
                renderer.lightProbeUsage = LightProbeUsage.Off;
                renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
                renderer.motionVectorGenerationMode = MotionVectorGenerationMode.ForceNoMotion;
                chunks.Add(new Chunk(child, renderer, mesh, count));
            }
            materialDirty = true;
            ApplyMaterialProperties();
        }

        private Mesh CreateChunkMesh(int start, int count)
        {
            int vertexCount = count * 4;
            var vertices = new Vector3[vertexCount];
            var uv0 = new Vector2[vertexCount];
            var indices = new int[count * 6];
            Vector2[] corners = { new Vector2(-1f, -1f), new Vector2(1f, -1f), new Vector2(1f, 1f), new Vector2(-1f, 1f) };
            for (int i = 0; i < count; ++i)
            {
                int v = i * 4;
                for (int corner = 0; corner < 4; ++corner)
                {
                    vertices[v + corner] = pointPositions[start + i];
                    uv0[v + corner] = corners[corner];
                }
                int t = i * 6;
                indices[t] = v;
                indices[t + 1] = v + 1;
                indices[t + 2] = v + 2;
                indices[t + 3] = v;
                indices[t + 4] = v + 2;
                indices[t + 5] = v + 3;
            }

            var mesh = new Mesh { name = "NeuralPointCloudChunk", indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(vertices);
            mesh.SetUVs(0, uv0);
            mesh.SetIndices(indices, MeshTopology.Triangles, 0, false);
            mesh.MarkDynamic();
            mesh.bounds = ComputeChunkBounds(start, count);
            return mesh;
        }

        private Bounds ComputeChunkBounds(int start, int count)
        {
            Vector3 minimum = pointPositions[start];
            Vector3 maximum = minimum;
            for (int i = 1; i < count; ++i)
            {
                Vector3 position = pointPositions[start + i];
                minimum = Vector3.Min(minimum, position);
                maximum = Vector3.Max(maximum, position);
            }
            Bounds bounds = new Bounds((minimum + maximum) * 0.5f, maximum - minimum);
            bounds.Expand(pointSize * 2f);
            return bounds;
        }

        private void UpdateChunkBounds()
        {
            if (pointPositions == null)
                return;
            int start = 0;
            for (int i = 0; i < chunks.Count; ++i)
            {
                Chunk chunk = chunks[i];
                chunk.SetBounds(ComputeChunkBounds(start, chunk.pointCount));
                start += chunk.pointCount;
            }
        }

        private void EnsureMaterial()
        {
            if (runtimeMaterial != null)
                return;
            Shader shader = renderMaterial != null ? renderMaterial.shader : Shader.Find(ShaderName);
            if (shader == null)
            {
                Debug.LogError($"{nameof(NeuralPointCloud)} requires a material using '{ShaderName}'. Assign renderMaterial to retain it in builds.", this);
                return;
            }
            runtimeMaterial = renderMaterial != null ? new Material(renderMaterial) : new Material(shader);
            runtimeMaterial.name = "Neural Point Cloud (Runtime)";
        }

        private void ApplyMaterialProperties()
        {
            EnsureMaterial();
            if (runtimeMaterial == null)
                return;
            runtimeMaterial.SetFloat("_PointSize", pointSize);
            runtimeMaterial.SetFloat("_RestingBrightness", restingBrightness);
            runtimeMaterial.SetFloat("_AfterglowSeconds", spikeAfterglowSeconds);
            runtimeMaterial.SetFloat("_DisplayGain", displayGain);
            runtimeMaterial.SetFloat("_DisplayTime", Time.unscaledTime);
            materialDirty = false;
        }

        private void ClearChunks()
        {
            for (int i = 0; i < chunks.Count; ++i)
                chunks[i].Dispose();
            chunks.Clear();
        }

        private static void DestroyOwnedObject(UnityEngine.Object target)
        {
            if (Application.isPlaying)
                Destroy(target);
            else
                DestroyImmediate(target);
        }

        private static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private sealed class Chunk
        {
            private readonly GameObject gameObject;
            private readonly MeshRenderer renderer;
            private readonly Mesh mesh;
            private readonly List<Color> colors;
            private readonly List<Vector2> times;
            public readonly int pointCount;

            public Chunk(GameObject gameObject, MeshRenderer renderer, Mesh mesh, int pointCount)
            {
                this.gameObject = gameObject;
                this.renderer = renderer;
                this.mesh = mesh;
                this.pointCount = pointCount;
                int vertices = pointCount * 4;
                colors = new List<Color>(vertices);
                times = new List<Vector2>(vertices);
                for (int i = 0; i < vertices; ++i)
                {
                    colors.Add(Color.clear);
                    times.Add(new Vector2(-10000f, 0f));
                }
                UploadActivity();
            }

            public void SetPoint(int index, Color activity, float spikeTime, bool preservePriorSpike)
            {
                int vertex = index * 4;
                if (preservePriorSpike)
                {
                    activity.r = colors[vertex].r;
                    spikeTime = times[vertex].x;
                }
                Vector2 time = new Vector2(spikeTime, 0f);
                for (int i = 0; i < 4; ++i)
                {
                    colors[vertex + i] = activity;
                    times[vertex + i] = time;
                }
            }

            public void ClearActivity()
            {
                for (int i = 0; i < colors.Count; ++i)
                {
                    colors[i] = Color.clear;
                    times[i] = new Vector2(-10000f, 0f);
                }
            }

            public void UploadActivity()
            {
                mesh.SetColors(colors);
                mesh.SetUVs(1, times);
            }

            public void SetMaterial(Material material)
            {
                renderer.sharedMaterial = material;
            }

            public void SetBounds(Bounds bounds)
            {
                mesh.bounds = bounds;
            }

            public void Dispose()
            {
                if (mesh != null)
                    DestroyOwnedObject(mesh);
                if (gameObject != null)
                    DestroyOwnedObject(gameObject);
            }
        }
    }
}
