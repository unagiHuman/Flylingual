using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

/// <summary>
/// Creates a visual-only comparison scene.  It deliberately never saves the
/// source replay scene and never writes to the PhysicsRig hierarchy.
/// </summary>
public static class FlyRealismBuilder
{
    const string SourceScene = "Assets/VisualDemo/WindowsReplayDemo.unity";
    const string RealismScene = "Assets/VisualDemo/SessionRealism/FlyRealismDemo.unity";
    const string SessionRoot = "Assets/FlyVisual/SessionRealism";
    const string BodyModel = SessionRoot + "/FlyVisual_Realism.fbx";
    const string LegModel = SessionRoot + "/FlyLegSegments_Realism.fbx";
    const string TextureRoot = SessionRoot + "/Textures";
    const string MaterialRoot = SessionRoot + "/Materials";
    const string SessionId = "01a09446-1c64-74c1-8579-f133826d2dd2";
    const int CaptureWidth = 1920;
    const int CaptureHeight = 1080;

    static readonly string[] RequiredTextures =
    {
        "Body_BaseColor.png", "Body_Normal.png", "Body_Mask.png",
        "Eye_BaseColor.png", "Eye_Normal.png", "Eye_Mask.png",
        "Wing_BaseColor.png", "Wing_Normal.png", "Wing_Mask.png"
    };

    [Serializable]
    sealed class RendererStatistics
    {
        public int rendererCount;
        public int triangleCount;
        public int textureCount;
        public long estimatedTextureBytes;
        public string[] textures;
    }

    [Serializable]
    sealed class RealismDiagnostic
    {
        public string utc;
        public string sourceScene;
        public string realismScene;
        public bool physicalSerializeEqual;
        public int physicalSerializeDiffCount;
        public int bindingCount;
        public int articulationJoints;
        public int footPads;
        public int visualPhysicsComponents;
        public string[] bindings;
        public RendererStatistics baseline;
        public RendererStatistics realism;
        public string physicsBefore;
        public string physicsBeforeSave;
        public string physicsAfterSave;
    }

    [MenuItem("FlyBrain/Visual Realism/Create Candidate Scene")]
    public static void CreateRealismDemo()
    {
        RequireSessionAssets();
        ConfigureImporters();
        EnsureDirectory("Assets/VisualDemo/SessionRealism");
        EnsureDirectory(MaterialRoot);
        Dictionary<string, Material> materials = CreateOrUpdateMaterials();

        Scene scene = EditorSceneManager.OpenScene(SourceScene, OpenSceneMode.Single);
        FlyBody body = RequireBody();
        VisualRigMapper mapper = RequireMapper();
        string physicsBefore = PhysicsSnapshot(body);
        RendererStatistics baseline = GatherRendererStatistics(mapper.transform);

        ReplaceThoraxVisual(mapper, materials);
        ReplaceLegVisuals(mapper, materials);
        VerifyVisualContract(body, mapper);
        string physicsBeforeSave = PhysicsSnapshot(body);
        if (!string.Equals(physicsBefore, physicsBeforeSave, StringComparison.Ordinal))
            throw new InvalidOperationException("Physics serialization changed while attaching the realism visuals.");

        if (!EditorSceneManager.SaveScene(scene, RealismScene))
            throw new IOException("Could not save realism candidate scene: " + RealismScene);
        AssetDatabase.SaveAssets();

        string physicsAfterSave = PhysicsSnapshot(body);
        if (!string.Equals(physicsBefore, physicsAfterSave, StringComparison.Ordinal))
            throw new InvalidOperationException("Physics serialization changed after saving the realism candidate scene.");

        PreserveSerializedParentAnchors();
        WriteDiagnostic(body, mapper, baseline, GatherRendererStatistics(mapper.transform), physicsBefore, physicsBeforeSave, physicsAfterSave);
        Debug.Log("FLY_REALISM_SCENE_CREATED bindings=25 joints=18 footPads=6 visualPhysics=0 physicalSerializeDiff=0");
    }

    static void PreserveSerializedParentAnchors()
    {
        // Unity recomputes auto-matched parent anchors when loading/saving a scene.
        // Retain the source decimal values in the candidate without changing any
        // live ArticulationBody property or the source scene itself.
        const string blockPattern = @"^--- !u!171741748 &(-?\d+)\n.*?(?=^--- !u!|\z)";
        const string anchorPattern = @"^  m_ParentAnchorPosition:.*$";
        var blocks = new Regex(blockPattern, RegexOptions.Multiline | RegexOptions.Singleline);
        var anchors = new Regex(anchorPattern, RegexOptions.Multiline);
        string source = File.ReadAllText(SourceScene).Replace("\r\n", "\n");
        string candidate = File.ReadAllText(RealismScene).Replace("\r\n", "\n");
        var originals = blocks.Matches(source).Cast<Match>().ToDictionary(m => m.Groups[1].Value, m => m.Value);
        int count = 0;
        string preserved = blocks.Replace(candidate, match =>
        {
            if (!originals.TryGetValue(match.Groups[1].Value, out string original)
                || anchors.Replace(original, "") != anchors.Replace(match.Value, ""))
                throw new InvalidOperationException("Unexpected serialized articulation change: " + match.Groups[1].Value);
            count++;
            return original;
        });
        if (count != originals.Count || count != 19)
            throw new InvalidOperationException("Expected the original thorax and 18 articulation joints.");
        if (preserved != candidate)
        {
            File.WriteAllText(RealismScene, preserved);
            AssetDatabase.ImportAsset(RealismScene, ImportAssetOptions.ForceUpdate);
        }
    }

    [MenuItem("FlyBrain/Visual Realism/Capture Neutral Comparison")]
    public static void CaptureNeutralComparison()
    {
        EnsureCandidateSceneExists();
        string output = CaptureOutput("neutral");
        CaptureComparison(output, true);
        Debug.Log("FLY_REALISM_CAPTURE_NEUTRAL " + output);
    }

    [MenuItem("FlyBrain/Visual Realism/Capture Game Lighting Comparison")]
    public static void CaptureGameLightingComparison()
    {
        EnsureCandidateSceneExists();
        string output = CaptureOutput("game-lighting");
        CaptureComparison(output, false);
        Debug.Log("FLY_REALISM_CAPTURE_GAME_LIGHTING " + output);
    }

    [MenuItem("FlyBrain/Visual Realism/Build Standalone OSX Candidate")]
    public static void BuildStandaloneOSX()
    {
        EnsureCandidateSceneExists();
        string output = Path.Combine(ArtifactRoot(), "player", "FlyRealismDemo.app");
        BuildStandaloneOSX(RealismScene, output, "candidate");
    }

    [MenuItem("FlyBrain/Visual Realism/Build Standalone OSX Baseline")]
    public static void BuildBaselineStandaloneOSX()
    {
        string output = Path.Combine(ArtifactRoot(), "player", "FlyBaselineVisualDemo.app");
        BuildStandaloneOSX(SourceScene, output, "baseline");
    }

    public static void CreateCaptureAndBuild()
    {
        CreateRealismDemo();
        CaptureNeutralComparison();
        CaptureGameLightingComparison();
        BuildStandaloneOSX();
        BuildBaselineStandaloneOSX();
    }

    static void BuildStandaloneOSX(string scene, string output, string label)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(output));
        BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { scene },
            locationPathName = output,
            target = BuildTarget.StandaloneOSX,
            options = BuildOptions.Development
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException("Standalone OSX " + label + " build failed: " + report.summary.result);
        Debug.Log("FLY_REALISM_OSX_BUILD_PASS kind=" + label + " " + output);
    }

    static void RequireSessionAssets()
    {
        RequireAssetFile(BodyModel);
        RequireAssetFile(LegModel);
        foreach (string texture in RequiredTextures) RequireAssetFile(TextureRoot + "/" + texture);
    }

    static void ConfigureImporters()
    {
        ConfigureModelImporter(BodyModel);
        ConfigureModelImporter(LegModel);
        ConfigureTextureImporter(TextureRoot + "/Body_BaseColor.png", false, true, false, false);
        ConfigureTextureImporter(TextureRoot + "/Body_Normal.png", true, false, false, false);
        ConfigureTextureImporter(TextureRoot + "/Body_Mask.png", false, false, true, false);
        ConfigureTextureImporter(TextureRoot + "/Eye_BaseColor.png", false, true, false, false);
        ConfigureTextureImporter(TextureRoot + "/Eye_Normal.png", true, false, false, false);
        ConfigureTextureImporter(TextureRoot + "/Eye_Mask.png", false, false, true, false);
        ConfigureTextureImporter(TextureRoot + "/Wing_BaseColor.png", false, true, true, true);
        ConfigureTextureImporter(TextureRoot + "/Wing_Normal.png", true, false, false, false);
        ConfigureTextureImporter(TextureRoot + "/Wing_Mask.png", false, false, true, false);
    }

    static void ConfigureModelImporter(string path)
    {
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
        ModelImporter importer = AssetImporter.GetAtPath(path) as ModelImporter;
        if (importer == null) throw new InvalidOperationException("Expected a ModelImporter: " + path);
        importer.importAnimation = false;
        // Keep the FBX slot names available for the strict six-material wiring.
        // The generated in-prefab placeholders are immediately replaced by the
        // independent SessionRealism Materials assets below.
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        importer.materialName = ModelImporterMaterialName.BasedOnMaterialName;
        importer.materialSearch = ModelImporterMaterialSearch.Local;
        importer.materialLocation = ModelImporterMaterialLocation.InPrefab;
        importer.importCameras = false;
        importer.importLights = false;
        importer.SaveAndReimport();
    }

    static void ConfigureTextureImporter(string path, bool normalMap, bool srgb, bool preserveAlpha, bool alphaIsTransparency)
    {
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
        TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer == null) throw new InvalidOperationException("Expected a TextureImporter: " + path);
        importer.textureType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
        importer.sRGBTexture = srgb;
        importer.alphaSource = preserveAlpha ? TextureImporterAlphaSource.FromInput : TextureImporterAlphaSource.None;
        importer.alphaIsTransparency = alphaIsTransparency;
        importer.mipmapEnabled = true;
        importer.SaveAndReimport();
    }

    static Dictionary<string, Material> CreateOrUpdateMaterials()
    {
        Texture2D bodyBase = LoadTexture("Body_BaseColor.png");
        Texture2D bodyNormal = LoadTexture("Body_Normal.png");
        Texture2D bodyMask = LoadTexture("Body_Mask.png");
        Texture2D eyeBase = LoadTexture("Eye_BaseColor.png");
        Texture2D eyeNormal = LoadTexture("Eye_Normal.png");
        Texture2D eyeMask = LoadTexture("Eye_Mask.png");
        Texture2D wingBase = LoadTexture("Wing_BaseColor.png");
        Texture2D wingNormal = LoadTexture("Wing_Normal.png");
        Texture2D wingMask = LoadTexture("Wing_Mask.png");

        var result = new Dictionary<string, Material>(StringComparer.Ordinal)
        {
            { "ChitinGold", CreateOrUpdateMaterial("ChitinGold", Color.white, 1f, bodyBase, bodyNormal, bodyMask, false) },
            { "AbdomenDark", CreateOrUpdateMaterial("AbdomenDark", new Color(.14f, .075f, .032f), 1f, bodyBase, bodyNormal, bodyMask, false) },
            { "EyeRuby", CreateOrUpdateMaterial("EyeRuby", Color.white, 1f, eyeBase, eyeNormal, eyeMask, false) },
            { "WingMembrane", CreateOrUpdateMaterial("WingMembrane", Color.white, 1f, wingBase, wingNormal, wingMask, true) },
            { "WingVein", CreateOrUpdateMaterial("WingVein", new Color(.28f, .19f, .095f), .32f, null, null, null, false) },
            { "Bristle", CreateOrUpdateMaterial("Bristle", new Color(.075f, .047f, .025f), .16f, null, null, null, false) }
        };
        return result;
    }

    static Material CreateOrUpdateMaterial(string name, Color color, float smoothness, Texture2D baseMap, Texture2D normalMap, Texture2D maskMap, bool transparent)
    {
        string path = MaterialRoot + "/" + name + ".mat";
        Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null) throw new InvalidOperationException("URP/Lit shader was not found.");
        if (material == null)
        {
            material = new Material(shader) { name = name };
            AssetDatabase.CreateAsset(material, path);
        }
        else material.shader = shader;

        material.name = name;
        material.SetColor("_BaseColor", color);
        material.SetColor("_Color", color);
        material.SetFloat("_Metallic", 0f);
        material.SetFloat("_Smoothness", smoothness);
        material.SetTexture("_BaseMap", baseMap);
        material.SetTexture("_BumpMap", normalMap);
        material.SetTexture("_MetallicGlossMap", maskMap);
        material.SetTexture("_OcclusionMap", maskMap);
        material.SetFloat("_SmoothnessTextureChannel", 0f);
        material.SetFloat("_OcclusionStrength", maskMap == null ? 0f : 1f);
        SetKeyword(material, "_NORMALMAP", normalMap != null);
        SetKeyword(material, "_METALLICSPECGLOSSMAP", maskMap != null);
        SetKeyword(material, "_OCCLUSIONMAP", maskMap != null);
        material.SetFloat("_Cull", transparent ? 0f : 2f);
        material.SetFloat("_Surface", transparent ? 1f : 0f);
        material.SetFloat("_ZWrite", transparent ? 0f : 1f);
        if (transparent)
        {
            material.SetFloat("_Blend", 0f);
            material.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.renderQueue = (int)RenderQueue.Transparent;
        }
        else
        {
            material.DisableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.renderQueue = -1;
        }
        EditorUtility.SetDirty(material);
        return material;
    }

    static void SetKeyword(Material material, string keyword, bool enabled)
    {
        if (enabled) material.EnableKeyword(keyword);
        else material.DisableKeyword(keyword);
    }

    static void ReplaceThoraxVisual(VisualRigMapper mapper, Dictionary<string, Material> materials)
    {
        VisualRigMapper.Binding thoraxBinding = mapper.bindings.SingleOrDefault(binding => binding.joint == "Thorax");
        if (thoraxBinding == null || thoraxBinding.visual == null)
            throw new InvalidOperationException("The Thorax VisualRig binding is missing.");

        Transform thoraxVisual = thoraxBinding.visual;
        UnpackDisplayRootIfNeeded(thoraxVisual);
        ClearVisualMeshChildren(thoraxVisual);
        GameObject candidate = InstantiateModel(BodyModel, "RealismBody", thoraxVisual);
        ApplyCandidateMaterials(candidate, materials);
        if (thoraxVisual.GetComponent<FlyWingBuzz>() == null) thoraxVisual.gameObject.AddComponent<FlyWingBuzz>();
    }

    static void ReplaceLegVisuals(VisualRigMapper mapper, Dictionary<string, Material> materials)
    {
        GameObject legAsset = AssetDatabase.LoadAssetAtPath<GameObject>(LegModel);
        if (legAsset == null) throw new InvalidOperationException("Leg FBX did not import: " + LegModel);

        foreach (VisualRigMapper.Binding binding in mapper.bindings)
        {
            if (binding.joint == "Thorax") continue;
            if (binding.visual == null) throw new InvalidOperationException("Visual binding has no visual Transform: " + binding.joint);
            string segment = SegmentName(binding.joint);
            Transform source = FindDescendant(legAsset.transform, segment);
            if (source == null) throw new InvalidOperationException("Leg FBX is missing its required mesh object: " + segment);

            ClearVisualMeshChildren(binding.visual);
            GameObject copy = UnityEngine.Object.Instantiate(source.gameObject);
            copy.name = "Realism_" + segment;
            copy.transform.SetParent(binding.visual, false);
            copy.transform.localPosition = Vector3.zero;
            copy.transform.localRotation = Quaternion.identity;
            copy.transform.localScale = Vector3.one;
            ApplyCandidateMaterials(copy, materials);
        }
    }

    static string SegmentName(string joint)
    {
        if (joint.EndsWith("_ThoraxBridge", StringComparison.Ordinal)) return "Bridge";
        if (joint.EndsWith("_Coxa", StringComparison.Ordinal)) return "Coxa";
        if (joint.EndsWith("_Femur", StringComparison.Ordinal)) return "Femur";
        if (joint.EndsWith("_Tibia", StringComparison.Ordinal)) return "Tibia";
        throw new InvalidOperationException("Unrecognized visual segment binding: " + joint);
    }

    static GameObject InstantiateModel(string assetPath, string name, Transform parent)
    {
        GameObject asset = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
        if (asset == null) throw new InvalidOperationException("Model did not import: " + assetPath);
        GameObject instance = PrefabUtility.InstantiatePrefab(asset) as GameObject;
        if (instance == null) throw new InvalidOperationException("Could not instantiate model: " + assetPath);
        instance.name = name;
        instance.transform.SetParent(parent, false);
        instance.transform.localPosition = Vector3.zero;
        instance.transform.localRotation = Quaternion.identity;
        instance.transform.localScale = Vector3.one;
        return instance;
    }

    static void UnpackDisplayRootIfNeeded(Transform displayRoot)
    {
        GameObject outermost = PrefabUtility.GetOutermostPrefabInstanceRoot(displayRoot.gameObject);
        if (outermost == null) return;
        if (outermost != displayRoot.gameObject)
            throw new InvalidOperationException("Thorax_Visual must remain the outermost display prefab root.");
        PrefabUtility.UnpackPrefabInstance(outermost, PrefabUnpackMode.OutermostRoot, InteractionMode.AutomatedAction);
    }

    static void ClearVisualMeshChildren(Transform root)
    {
        for (int index = root.childCount - 1; index >= 0; index--)
            UnityEngine.Object.DestroyImmediate(root.GetChild(index).gameObject);
        foreach (Renderer renderer in root.GetComponents<Renderer>()) UnityEngine.Object.DestroyImmediate(renderer);
        foreach (MeshFilter meshFilter in root.GetComponents<MeshFilter>()) UnityEngine.Object.DestroyImmediate(meshFilter);
    }

    static void ApplyCandidateMaterials(GameObject root, Dictionary<string, Material> materials)
    {
        foreach (Renderer renderer in root.GetComponentsInChildren<Renderer>(true))
        {
            Material[] slots = renderer.sharedMaterials;
            if (slots == null || slots.Length == 0)
                throw new InvalidOperationException("Candidate renderer has no named material slot: " + renderer.name);
            for (int index = 0; index < slots.Length; index++)
            {
                string slotName = slots[index] == null ? string.Empty : slots[index].name;
                Material material;
                if (!materials.TryGetValue(slotName, out material))
                    throw new InvalidOperationException("Candidate renderer uses an unsupported material slot '" + slotName + "' on " + renderer.name);
                slots[index] = material;
            }
            renderer.sharedMaterials = slots;
        }
    }

    static void VerifyVisualContract(FlyBody body, VisualRigMapper mapper)
    {
        if (mapper.bindings == null || mapper.bindings.Length != 25)
            throw new InvalidOperationException("Expected 25 preserved VisualRig bindings.");
        if (body.GetComponentsInChildren<FlyJoint>(true).Length != 18)
            throw new InvalidOperationException("Expected 18 physics joints.");
        if (body.GetComponentsInChildren<FlyFootContact>(true).Length != 6)
            throw new InvalidOperationException("Expected 6 FootPad contact components.");
        int visualPhysics = mapper.GetComponentsInChildren<Collider>(true).Length +
                            mapper.GetComponentsInChildren<Rigidbody>(true).Length +
                            mapper.GetComponentsInChildren<ArticulationBody>(true).Length;
        if (visualPhysics != 0) throw new InvalidOperationException("The candidate VisualRig contains physics components.");
        foreach (VisualRigMapper.Binding binding in mapper.bindings)
            if (binding.visual == null || binding.physics == null)
                throw new InvalidOperationException("VisualRig binding was broken: " + binding.joint);
    }

    static void WriteDiagnostic(FlyBody body, VisualRigMapper mapper, RendererStatistics baseline, RendererStatistics realism, string before, string beforeSave, string afterSave)
    {
        int visualPhysics = mapper.GetComponentsInChildren<Collider>(true).Length +
                            mapper.GetComponentsInChildren<Rigidbody>(true).Length +
                            mapper.GetComponentsInChildren<ArticulationBody>(true).Length;
        var diagnostic = new RealismDiagnostic
        {
            utc = DateTime.UtcNow.ToString("o"),
            sourceScene = SourceScene,
            realismScene = RealismScene,
            physicalSerializeEqual = before == beforeSave && before == afterSave,
            physicalSerializeDiffCount = PhysicsDiffCount(before, afterSave),
            bindingCount = mapper.bindings.Length,
            articulationJoints = body.GetComponentsInChildren<FlyJoint>(true).Length,
            footPads = body.GetComponentsInChildren<FlyFootContact>(true).Length,
            visualPhysicsComponents = visualPhysics,
            bindings = mapper.bindings.Select(binding => binding.joint).ToArray(),
            baseline = baseline,
            realism = realism,
            physicsBefore = before,
            physicsBeforeSave = beforeSave,
            physicsAfterSave = afterSave
        };
        string path = Path.Combine(ArtifactRoot(), "fly_realism_diagnostic.json");
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllText(path, JsonUtility.ToJson(diagnostic, true));
        var layout = new RigLayout
        {
            coordinateSystem = "Unity +Z forward +Y up; relative to Thorax_Visual",
            bindings = mapper.bindings.Select(binding => new RigPose
            {
                joint = binding.joint,
                matrix = MatrixValues(mapper.bindings.Single(x => x.joint == "Thorax").visual.worldToLocalMatrix * binding.visual.localToWorldMatrix)
            }).ToArray()
        };
        File.WriteAllText(Path.Combine(ArtifactRoot(), "rig-layout.json"), JsonUtility.ToJson(layout, true));
    }

    [Serializable] sealed class RigLayout { public string coordinateSystem; public RigPose[] bindings; }
    [Serializable] sealed class RigPose { public string joint; public float[] matrix; }
    static float[] MatrixValues(Matrix4x4 matrix)
    {
        var values = new float[16];
        for (int row = 0; row < 4; row++) for (int col = 0; col < 4; col++) values[row * 4 + col] = matrix[row, col];
        return values;
    }

    static string PhysicsSnapshot(FlyBody body)
    {
        var records = new List<string>();
        foreach (Transform transform in body.GetComponentsInChildren<Transform>(true))
            records.Add("Transform|" + TransformPath(body.transform, transform) + "|" + EditorJsonUtility.ToJson(transform));
        foreach (Component component in body.GetComponentsInChildren<Component>(true))
        {
            if (component == null || component is Transform) continue;
            if (component is ArticulationBody || component is Collider || component is FlyBody || component is FlyLeg ||
                component is FlyJoint || component is FlyFootContact || component is FlyFootAdhesion)
                records.Add(component.GetType().FullName + "|" + TransformPath(body.transform, component.transform) + "|" + EditorJsonUtility.ToJson(component));
        }
        if (body.Config != null) records.Add("FlyLocomotionConfig|" + EditorJsonUtility.ToJson(body.Config));
        records.Sort(StringComparer.Ordinal);
        return string.Join("\n", records);
    }

    static int PhysicsDiffCount(string before, string after)
    {
        if (before == after) return 0;
        string[] a = before.Split('\n');
        string[] b = after.Split('\n');
        int count = Math.Abs(a.Length - b.Length);
        for (int index = 0; index < Math.Min(a.Length, b.Length); index++) if (a[index] != b[index]) count++;
        return count;
    }

    static RendererStatistics GatherRendererStatistics(Transform root)
    {
        var texturePaths = new HashSet<string>(StringComparer.Ordinal);
        var textures = new HashSet<Texture>();
        int triangles = 0;
        Renderer[] renderers = root.GetComponentsInChildren<Renderer>(true);
        foreach (Renderer renderer in renderers)
        {
            MeshFilter filter = renderer.GetComponent<MeshFilter>();
            Mesh mesh = filter == null ? null : filter.sharedMesh;
            if (mesh != null)
                for (int subMesh = 0; subMesh < mesh.subMeshCount; subMesh++) triangles += (int)(mesh.GetIndexCount(subMesh) / 3);
            foreach (Material material in renderer.sharedMaterials)
            {
                if (material == null) continue;
                foreach (string property in material.GetTexturePropertyNames())
                {
                    Texture texture = material.GetTexture(property);
                    if (texture == null || !textures.Add(texture)) continue;
                    string path = AssetDatabase.GetAssetPath(texture);
                    texturePaths.Add(string.IsNullOrEmpty(path) ? texture.name : path);
                }
            }
        }
        long bytes = textures.OfType<Texture2D>().Sum(texture => (long)texture.width * texture.height * 4L);
        return new RendererStatistics
        {
            rendererCount = renderers.Length,
            triangleCount = triangles,
            textureCount = textures.Count,
            estimatedTextureBytes = bytes,
            textures = texturePaths.OrderBy(path => path, StringComparer.Ordinal).ToArray()
        };
    }

    static void CaptureComparison(string output, bool neutralLighting)
    {
        CaptureScene(SourceScene, Path.Combine(output, "baseline"), neutralLighting);
        CaptureScene(RealismScene, Path.Combine(output, "realism"), neutralLighting);
    }

    public static void CaptureScene(string scenePath, string output, bool neutralLighting)
    {
        EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
        Directory.CreateDirectory(output);
        FlyBody body = RequireBody();
        VisualRigMapper mapper = RequireMapper();
        Camera source = Camera.main;
        if (source == null) throw new InvalidOperationException("The comparison scene has no Main Camera.");
        GameObject cameraObject = new GameObject("SessionRealismCaptureCamera") { hideFlags = HideFlags.HideAndDontSave };
        Camera camera = cameraObject.AddComponent<Camera>();
        camera.CopyFrom(source);
        camera.rect = new Rect(0f, 0f, 1f, 1f);
        camera.enabled = false;

        NeutralLighting lighting = neutralLighting ? NeutralLighting.Create() : null;
        try
        {
            Vector3 center = body.Thorax.transform.position + body.Thorax.transform.up * .18f;
            CaptureShot(camera, Path.Combine(output, "front.png"), center + body.Thorax.transform.forward * 8f + Vector3.up * 1.6f, center, 43f);
            CaptureShot(camera, Path.Combine(output, "side.png"), center + body.Thorax.transform.right * 8f + Vector3.up * 1.6f, center, 43f);
            CaptureShot(camera, Path.Combine(output, "top.png"), center + Vector3.up * 9f + body.Thorax.transform.forward * .02f, center, 43f);
            CaptureShot(camera, Path.Combine(output, "oblique.png"), center + (body.Thorax.transform.forward + body.Thorax.transform.right).normalized * 7.5f + Vector3.up * 4.2f, center, 43f);
            Vector3 head = body.Thorax.transform.position + body.Thorax.transform.forward * 1.12f + Vector3.up * .10f;
            CaptureShot(camera, Path.Combine(output, "eye-close.png"), head + body.Thorax.transform.forward * 2.2f + body.Thorax.transform.right * .7f + Vector3.up * .55f, head, 34f);
            Vector3 wingCenter = body.Thorax.transform.position - body.Thorax.transform.forward * 1.25f + body.Thorax.transform.right * .75f + Vector3.up * .32f;
            CaptureShot(camera, Path.Combine(output, "wing-close.png"), wingCenter + body.Thorax.transform.right * .6f + Vector3.up * 3.7f, wingCenter, 42f);
            CaptureWingBackgrounds(camera, mapper.transform, wingCenter, body.Thorax.transform.right, output);
        }
        finally
        {
            if (lighting != null) lighting.Dispose();
            UnityEngine.Object.DestroyImmediate(cameraObject);
        }

        if (mapper.bindings.Length != 25) throw new InvalidOperationException("Comparison scene no longer has 25 VisualRig bindings.");
    }

    static void CaptureWingBackgrounds(Camera camera, Transform visual, Vector3 wingCenter, Vector3 right, string output)
    {
        Transform[] objects = visual.GetComponentsInChildren<Transform>(true);
        int[] layers = objects.Select(item => item.gameObject.layer).ToArray();
        int mask = camera.cullingMask;
        Color background = camera.backgroundColor;
        CameraClearFlags flags = camera.clearFlags;
        try
        {
            foreach (Transform item in objects) item.gameObject.layer = 31;
            camera.cullingMask = 1 << 31;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(.91f, .91f, .91f);
            CaptureShot(camera, Path.Combine(output, "wing-light-background.png"), wingCenter + right * .6f + Vector3.up * 3.7f, wingCenter, 42f);
            camera.backgroundColor = new Color(.025f, .025f, .025f);
            CaptureShot(camera, Path.Combine(output, "wing-underside.png"), wingCenter + right * 2.6f - Vector3.up * .65f, wingCenter, 46f);
        }
        finally
        {
            for (int index = 0; index < objects.Length; index++) objects[index].gameObject.layer = layers[index];
            camera.cullingMask = mask;
            camera.backgroundColor = background;
            camera.clearFlags = flags;
        }
    }

    static void CaptureShot(Camera camera, string path, Vector3 position, Vector3 target, float fieldOfView)
    {
        camera.transform.position = position;
        camera.transform.rotation = Quaternion.LookRotation(target - position, Vector3.up);
        camera.fieldOfView = fieldOfView;
        RenderTexture targetTexture = RenderTexture.GetTemporary(CaptureWidth, CaptureHeight, 24, RenderTextureFormat.ARGB32);
        RenderTexture previous = RenderTexture.active;
        try
        {
            camera.targetTexture = targetTexture;
            camera.Render();
            RenderTexture.active = targetTexture;
            var image = new Texture2D(CaptureWidth, CaptureHeight, TextureFormat.RGBA32, false);
            image.ReadPixels(new Rect(0f, 0f, CaptureWidth, CaptureHeight), 0, 0);
            image.Apply(false, false);
            File.WriteAllBytes(path, image.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(image);
        }
        finally
        {
            camera.targetTexture = null;
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(targetTexture);
        }
    }

    sealed class NeutralLighting : IDisposable
    {
        readonly List<LightState> originalLights;
        readonly Color ambient;
        readonly AmbientMode ambientMode;
        readonly float reflectionIntensity;
        readonly bool fog;
        readonly List<GameObject> created = new List<GameObject>();

        NeutralLighting(List<LightState> originalLights, Color ambient, AmbientMode ambientMode, float reflectionIntensity, bool fog)
        {
            this.originalLights = originalLights;
            this.ambient = ambient;
            this.ambientMode = ambientMode;
            this.reflectionIntensity = reflectionIntensity;
            this.fog = fog;
        }

        public static NeutralLighting Create()
        {
            var states = UnityEngine.Object.FindObjectsByType<Light>(FindObjectsInactive.Include, FindObjectsSortMode.None)
                .Select(light => new LightState { light = light, enabled = light.enabled }).ToList();
            foreach (LightState state in states) state.light.enabled = false;
            var result = new NeutralLighting(states, RenderSettings.ambientLight, RenderSettings.ambientMode, RenderSettings.reflectionIntensity, RenderSettings.fog);
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(.30f, .30f, .30f);
            RenderSettings.reflectionIntensity = .5f;
            RenderSettings.fog = false;
            result.AddLight("Neutral key", new Vector3(35f, -35f, 0f), Color.white, 2.1f);
            result.AddLight("Neutral fill", new Vector3(45f, 140f, 0f), Color.white, .85f);
            result.AddLight("Neutral rim", new Vector3(-35f, -150f, 0f), Color.white, 1.05f);
            return result;
        }

        void AddLight(string name, Vector3 euler, Color color, float intensity)
        {
            GameObject item = new GameObject(name) { hideFlags = HideFlags.HideAndDontSave };
            Light light = item.AddComponent<Light>();
            light.type = LightType.Directional;
            light.color = color;
            light.intensity = intensity;
            light.shadows = LightShadows.Soft;
            item.transform.rotation = Quaternion.Euler(euler);
            created.Add(item);
        }

        public void Dispose()
        {
            foreach (GameObject item in created) if (item != null) UnityEngine.Object.DestroyImmediate(item);
            foreach (LightState state in originalLights) if (state.light != null) state.light.enabled = state.enabled;
            RenderSettings.ambientLight = ambient;
            RenderSettings.ambientMode = ambientMode;
            RenderSettings.reflectionIntensity = reflectionIntensity;
            RenderSettings.fog = fog;
        }

        sealed class LightState { public Light light; public bool enabled; }
    }

    static FlyBody RequireBody()
    {
        FlyBody body = UnityEngine.Object.FindFirstObjectByType<FlyBody>(FindObjectsInactive.Include);
        if (body == null) throw new InvalidOperationException("The replay scene does not contain FlyBody.");
        return body;
    }

    static VisualRigMapper RequireMapper()
    {
        VisualRigMapper mapper = UnityEngine.Object.FindFirstObjectByType<VisualRigMapper>(FindObjectsInactive.Include);
        if (mapper == null) throw new InvalidOperationException("The replay scene does not contain VisualRigMapper.");
        return mapper;
    }

    static Texture2D LoadTexture(string name)
    {
        Texture2D texture = AssetDatabase.LoadAssetAtPath<Texture2D>(TextureRoot + "/" + name);
        if (texture == null) throw new InvalidOperationException("Required realism texture did not import: " + name);
        return texture;
    }

    static Transform FindDescendant(Transform root, string name)
    {
        if (root.name == name) return root;
        foreach (Transform descendant in root.GetComponentsInChildren<Transform>(true)) if (descendant.name == name) return descendant;
        return null;
    }

    static void RequireAssetFile(string assetPath)
    {
        string absolutePath = Path.GetFullPath(Path.Combine(Application.dataPath, "../" + assetPath));
        if (!File.Exists(absolutePath)) throw new FileNotFoundException("Required session realism asset is missing. Generate it before Unity integration.", absolutePath);
    }

    static void EnsureCandidateSceneExists()
    {
        if (AssetDatabase.LoadAssetAtPath<SceneAsset>(RealismScene) == null)
            throw new FileNotFoundException("CreateRealismDemo must succeed before capture or player build.", RealismScene);
    }

    static string TransformPath(Transform root, Transform item)
    {
        var names = new List<string>();
        for (Transform current = item; current != null; current = current.parent)
        {
            names.Add(current.name);
            if (current == root) break;
        }
        names.Reverse();
        return string.Join("/", names);
    }

    static void EnsureDirectory(string assetDirectory)
    {
        string absolutePath = Path.GetFullPath(Path.Combine(Application.dataPath, "../" + assetDirectory));
        Directory.CreateDirectory(absolutePath);
    }

    static string RepoRoot() => Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
    static string ArtifactRoot() => Path.Combine(RepoRoot(), "artifacts", "sessions", SessionId, "unity");
    static string CaptureOutput(string kind)
    {
        string output = Path.Combine(ArtifactRoot(), kind);
        Directory.CreateDirectory(output);
        return output;
    }
}
