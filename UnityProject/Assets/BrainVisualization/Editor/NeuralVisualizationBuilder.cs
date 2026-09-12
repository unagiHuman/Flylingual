using System;
using System.IO;
using FlyBrainPoC;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.Universal;

namespace FlyBrainVisualization.Editor
{
    /// <summary>Generates only this feature's assets. Existing scenes and project settings are untouched.</summary>
    public static class NeuralVisualizationBuilder
    {
        private const string Folder = "Assets/BrainVisualization/Generated";
        private const string PrefabPath = Folder + "/NeuralObservatory.prefab";
        private const string MaterialPath = Folder + "/NeuralPoints.mat";
        private const string AtlasPath = "Assets/BrainVisualization/Resources/BrainVisualization/malecns-atlas.json";

        [MenuItem("Tools/FlyBrain/Neural Visualization/1 Generate Prefab")]
        public static void GenerateAssets()
        {
            AssetDatabase.Refresh();
            if (!AssetDatabase.IsValidFolder(Folder)) AssetDatabase.CreateFolder("Assets/BrainVisualization", "Generated");
            Shader shader = AssetDatabase.LoadAssetAtPath<Shader>("Assets/BrainVisualization/Rendering/NeuralPointCloud.shader");
            if (shader == null) throw new InvalidOperationException("Neural point shader is missing");
            foreach (var message in ShaderUtil.GetShaderMessages(shader))
                if (message.severity == UnityEditor.Rendering.ShaderCompilerMessageSeverity.Error)
                    throw new InvalidOperationException("Neural shader compile error: " + message.message);
            var atlas = AssetDatabase.LoadAssetAtPath<TextAsset>(AtlasPath);
            if (atlas == null) throw new InvalidOperationException("Export malecns-atlas.json first; see Neural-Visualization.md");
            var material = AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
            if (material == null) { material = new Material(shader); AssetDatabase.CreateAsset(material, MaterialPath); }
            var root = new GameObject("NeuralObservatory");
            root.SetActive(false);
            // A dedicated off-world rendering stage prevents gameplay camera/lighting changes.
            var stage = new GameObject("AnatomicalDisplay"); stage.transform.SetParent(root.transform, false);
            stage.transform.localPosition = new Vector3(0, -10000, 0); stage.layer = 31;
            var cloudObject = new GameObject("NeuronSomata"); cloudObject.transform.SetParent(stage.transform, false); cloudObject.layer = 31;
            cloudObject.transform.localRotation = Quaternion.Euler(0, 12, 0);
            var cloud = cloudObject.AddComponent<NeuralPointCloud>();
            var serialized = new SerializedObject(cloud);
            serialized.FindProperty("renderMaterial").objectReferenceValue = material; serialized.ApplyModifiedPropertiesWithoutUndo();
            var cameraObject = new GameObject("BrainCamera"); cameraObject.transform.SetParent(stage.transform, false);
            cameraObject.transform.localPosition = new Vector3(0, 0, -4);
            var camera = cameraObject.AddComponent<Camera>();
            camera.orthographic = true; camera.orthographicSize = 1.25f; camera.nearClipPlane = .1f; camera.farClipPlane = 10;
            camera.clearFlags = CameraClearFlags.SolidColor; camera.backgroundColor = new Color(.025f, .044f, .072f, 1);
            camera.cullingMask = 1 << 31; camera.allowHDR = false; camera.allowMSAA = false; camera.enabled = false;
            var additional = cameraObject.AddComponent<UniversalAdditionalCameraData>();
            additional.renderPostProcessing = false; additional.renderShadows = false;
            var observer = root.AddComponent<NeuralActivityObserver>(); observer.Configure(null, atlas, cloud);
            var panel = root.AddComponent<NeuralVisualizationPanel>(); panel.Configure(observer, cloud, camera, cloudObject.transform);
            root.SetActive(true);
            try { PrefabUtility.SaveAsPrefabAsset(root, PrefabPath); }
            finally { UnityEngine.Object.DestroyImmediate(root); }
            AssetDatabase.SaveAssets();
            Debug.Log("NEURAL_VIS_PREFAB_READY: " + PrefabPath + " (no gameplay scene modified)");
        }

        [MenuItem("Tools/FlyBrain/Neural Visualization/2 Add To Current Scene")]
        public static void AddToCurrentScene()
        {
            if (UnityEngine.Object.FindAnyObjectByType<NeuralVisualizationPanel>() != null)
            { Debug.LogWarning("A Neural Observatory already exists in this scene"); return; }
            var clients = UnityEngine.Object.FindObjectsByType<BrainTcpClient>();
            if (clients.Length != 1) throw new InvalidOperationException("Select a scene with exactly one existing BrainTcpClient; no new TCP client will be created");
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            if (prefab == null) { GenerateAssets(); prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath); }
            var root = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            Undo.RegisterCreatedObjectUndo(root, "Add Neural Observatory");
            root.GetComponent<NeuralActivityObserver>().Configure(clients[0], AssetDatabase.LoadAssetAtPath<TextAsset>(AtlasPath), root.GetComponentInChildren<NeuralPointCloud>(true));
            Selection.activeGameObject = root;
            EditorSceneManager.MarkSceneDirty(root.scene); // User chooses whether/where to save.
        }

        // Editor-only static anatomy rendering; does not enter PlayMode or create a brain connection.
        [MenuItem("Tools/FlyBrain/Neural Visualization/3 Export Static Anatomy Preview")]
        public static void ExportStaticPreview()
        {
            GenerateAssets();
            var scene = EditorSceneManager.NewPreviewScene();
            RenderTexture texture = null; Texture2D image = null;
            try
            {
                var root = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath), scene);
                var atlas = JsonUtility.FromJson<NeuralAtlas>(AssetDatabase.LoadAssetAtPath<TextAsset>(AtlasPath).text);
                var positions = new Vector3[atlas.neurons.Length];
                for (int i = 0; i < positions.Length; i++) positions[i] = new Vector3(atlas.neurons[i].x, atlas.neurons[i].y, atlas.neurons[i].z);
                root.GetComponentInChildren<NeuralPointCloud>().SetPoints(positions);
                var camera = root.GetComponentInChildren<Camera>(); camera.scene = scene;
                texture = new RenderTexture(1000, 1000, 24); texture.Create(); camera.targetTexture = texture;
                camera.Render();
                var old = RenderTexture.active;
                try
                {
                    RenderTexture.active = texture; image = new Texture2D(1000, 1000, TextureFormat.RGB24, false);
                    image.ReadPixels(new Rect(0, 0, 1000, 1000), 0, 0); image.Apply();
                }
                finally { RenderTexture.active = old; }
                string folder = Path.GetFullPath(Path.Combine(Application.dataPath, "../../artifacts/neural-visualization"));
                Directory.CreateDirectory(folder); File.WriteAllBytes(Path.Combine(folder, "static-anatomy.png"), image.EncodeToPNG());
                Debug.Log("NEURAL_VIS_STATIC_PREVIEW: " + folder + "/static-anatomy.png; static soma coordinates only, no activity simulation");
            }
            finally
            {
                EditorSceneManager.ClosePreviewScene(scene);
                if (texture != null) { texture.Release(); UnityEngine.Object.DestroyImmediate(texture); }
                if (image != null) UnityEngine.Object.DestroyImmediate(image);
            }
        }
    }
}
