using System;
using System.IO;
using System.Linq;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

// Session candidate only. Retains all joint names, parents, local offsets,
// segment dimensions and bone-local hinge axes from the existing rig.
public static class FlyGroundedRealismBuilder
{
    public const string ScenePath = "Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity";
    public const string ReviewScenePath = "Assets/VisualDemo/SessionRealism/FlyGroundedContactReview.unity";
    const string ConfigPath = "Assets/VisualDemo/SessionRealism/FlyGroundedLocomotionConfig.asset";
    const string Source = "Assets/VisualDemo/SessionRealism/FlyRealismDemo.unity";
    const string SessionId = "01a09446-1c64-74c1-8579-f133826d2dd2";
    static string Output => Path.GetFullPath(Path.Combine(Application.dataPath, "../../artifacts/sessions", SessionId, "unity/grounded"));

    [Serializable] sealed class LegLayout
    {
        public string leg;
        public Vector3 hip, knee, foot, sole;
        public float footBottom;
    }
    [Serializable] sealed class Layout
    {
        public string evidence = "Editor static pose; runtime contact is recorded separately";
        public int joints, feet, bindings;
        public bool boneLocalOffsetsAndAxesPreserved;
        public LegLayout[] legs;
    }

    [MenuItem("FlyBrain/Visual Realism/Create Grounded Candidate")]
    public static void Create()
    {
        var scene = EditorSceneManager.OpenScene(Source, OpenSceneMode.Single);
        var body = UnityEngine.Object.FindFirstObjectByType<FlyBody>();
        var demo = UnityEngine.Object.FindFirstObjectByType<WindowsReplayDemo>();
        var mapper = UnityEngine.Object.FindFirstObjectByType<VisualRigMapper>();
        if (body == null || demo == null || mapper == null) throw new InvalidOperationException("Missing candidate rig.");
        string contract = SkeletonContract(body);
        FlyLocomotionConfig config = AssetDatabase.LoadAssetAtPath<FlyLocomotionConfig>(ConfigPath);
        if (config == null)
        {
            config = UnityEngine.Object.Instantiate(body.Config);
            config.name = "FlyGroundedLocomotionConfig";
            AssetDatabase.CreateAsset(config, ConfigPath);
        }
        else EditorUtility.CopySerialized(body.Config, config);
        config.groundedTripodGait = true;
        config.coxaStrideAmplitudeDegrees = 24f;
        config.femurLiftAmplitudeDegrees = 24f;
        config.tibiaLiftAmplitudeDegrees = 16f;
        EditorUtility.SetDirty(config);
        SetReference(body, "config", config);
        SetReference(demo.controller, "config", config);

        foreach (FlyLeg leg in body.Legs)
        {
            float side = leg.LeftSide ? -1f : 1f;
            float fore = leg.LegId.EndsWith("F") ? .32f : leg.LegId.EndsWith("H") ? -.32f : 0f;
            Vector3 outward = new Vector3(side, 0f, fore).normalized;
            // Coxa swings about vertical; femur/tibia flex about the horizontal
            // tangent to the radial leg plane. The local anchor rotation stays.
            Vector3 tangent = Vector3.Cross(outward, Vector3.up) * side;
            Aim(leg.Coxa, outward, Vector3.up);
            Aim(leg.Femur, outward - Vector3.up * .28f, tangent);
            Aim(leg.Tibia, outward * .20f - Vector3.up, tangent);
        }
        Physics.SyncTransforms();
        // Keep the source spawn height. PhysX resolves the nonuniformly scaled
        // articulation at startup; lowering by an Editor-only bounds estimate
        // can put the initial physical legs through the floor.
        foreach (FlyLeg leg in body.Legs)
        {
            var binding = mapper.bindings.Single(b => b.joint == leg.LegId + "_Tibia");
            var endpointObject = new GameObject(leg.LegId + "_SoleVisualEndpoint");
            endpointObject.transform.SetParent(mapper.transform, false);
            var endpoint = endpointObject.AddComponent<FlySoleVisualEndpoint>();
            endpoint.foot = leg.FootContact.GetComponent<SphereCollider>();
            endpoint.contact = leg.FootContact;
            endpoint.thorax = body.Thorax.transform;
            endpoint.Refresh();
            binding.physicsTip = endpoint.transform;
        }
        mapper.SendMessage("LateUpdate", SendMessageOptions.RequireReceiver);
        if (contract != SkeletonContract(body)) throw new InvalidOperationException("Bone structure or collider geometry changed.");
        if (mapper.bindings.Length != 25 || body.Legs.Count != 6) throw new InvalidOperationException("Candidate rig contract failed.");
        if (!EditorSceneManager.SaveScene(scene, ScenePath)) throw new IOException("Could not save grounded candidate.");
        AssetDatabase.SaveAssets();
        Directory.CreateDirectory(Output);
        File.WriteAllText(Path.Combine(Output, "static-layout.json"), JsonUtility.ToJson(new Layout
        {
            joints = body.GetComponentsInChildren<FlyJoint>().Length,
            feet = body.Legs.Count,
            bindings = mapper.bindings.Length,
            boneLocalOffsetsAndAxesPreserved = true,
            legs = body.Legs.Select(leg => new LegLayout
            {
                leg = leg.LegId, hip = leg.Femur.transform.position, knee = leg.Tibia.transform.position,
                foot = leg.FootProbePosition,
                sole = mapper.bindings.Single(b => b.joint == leg.LegId + "_Tibia").physicsTip.position,
                footBottom = FootBottom(leg)
            }).ToArray()
        }, true));
        Debug.Log("FLY_GROUNDED_CANDIDATE_CREATED joints=18 feet=6 bindings=25 boneStructurePreserved=true");
    }

    static void Aim(FlyJoint joint, Vector3 direction, Vector3 axis)
    {
        Transform t = joint.transform;
        t.localRotation = Quaternion.LookRotation(t.parent.InverseTransformVector(direction), t.parent.InverseTransformVector(axis));
        var articulation = joint.Articulation;
        articulation.matchAnchors = false;
        articulation.parentAnchorPosition = t.localPosition;
        articulation.parentAnchorRotation = t.localRotation * articulation.anchorRotation;
    }

    static float FootBottom(FlyLeg leg)
    {
        var sphere = leg.FootContact.GetComponent<SphereCollider>();
        Vector3 s = sphere.transform.lossyScale;
        return sphere.transform.TransformPoint(sphere.center).y - sphere.radius * Mathf.Max(Mathf.Abs(s.x), Mathf.Abs(s.y), Mathf.Abs(s.z));
    }

    static void SetReference(UnityEngine.Object owner, string property, UnityEngine.Object value)
    {
        var serialized = new SerializedObject(owner);
        serialized.FindProperty(property).objectReferenceValue = value;
        serialized.ApplyModifiedPropertiesWithoutUndo();
    }

    static string SkeletonContract(FlyBody body)
    {
        return string.Join("\n", body.GetComponentsInChildren<Transform>().OrderBy(t => t.name).Select(t =>
        {
            var ab = t.GetComponent<ArticulationBody>();
            return t.name + "|" + t.parent?.name + "|" + (t == body.Thorax.transform ? "root" : t.localPosition.ToString("R"))
                + "|" + t.localScale.ToString("R") + "|" + (ab == null ? "" : ab.anchorRotation.ToString("R"))
                + "|" + string.Join(";", t.GetComponents<Collider>().Select(c => EditorJsonUtility.ToJson(c)));
        }));
    }

    [MenuItem("FlyBrain/Visual Realism/Build Grounded Candidate OSX")]
    public static void Build()
    {
        BuildScene(ScenePath, "FlyGroundedRealism.app");
    }

    static void BuildScene(string scenePath, string appName)
    {
        Directory.CreateDirectory(Output);
        var result = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { scenePath }, locationPathName = Path.Combine(Output, appName),
            target = BuildTarget.StandaloneOSX, options = BuildOptions.Development
        });
        if (result.summary.result != BuildResult.Succeeded) throw new InvalidOperationException("Grounded candidate build failed.");
        Debug.Log("FLY_GROUNDED_BUILD_PASS");
    }

    public static void CreateCaptureAndBuild()
    {
        Create();
        FlyRealismBuilder.CaptureScene(ScenePath, Path.Combine(Output, "static"), true);
        Build();
    }

    [MenuItem("FlyBrain/Visual Realism/Create Flat Contact Review")]
    public static void CreateFlatReview()
    {
        var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        var body = UnityEngine.Object.FindAnyObjectByType<FlyBody>();
        var mapper = UnityEngine.Object.FindAnyObjectByType<VisualRigMapper>();
        var floor = GameObject.Find("Ground");
        if (floor == null) throw new InvalidOperationException("Flat review requires the base Ground object.");
        floor.transform.localScale = new Vector3(40f, .2f, 80f);
        foreach (Collider collider in UnityEngine.Object.FindObjectsByType<Collider>(FindObjectsInactive.Exclude))
        {
            // Course props also carry FlyGroundMarker, so select the actual
            // base floor explicitly instead of retaining every adhesive prop.
            if (collider.transform.IsChildOf(body.transform) || collider.name == "Ground") continue;
            collider.gameObject.SetActive(false);
        }
        foreach (Renderer renderer in UnityEngine.Object.FindObjectsByType<Renderer>(FindObjectsInactive.Exclude))
            if (!renderer.transform.IsChildOf(body.transform) && !renderer.transform.IsChildOf(mapper.transform) && renderer.name != "Ground")
                renderer.enabled = false;
        var game = UnityEngine.Object.FindAnyObjectByType<AscentGameSession>();
        if (game != null) game.enabled = false;
        Camera.main.rect = new Rect(0f, 0f, 1f, 1f);
        if (!EditorSceneManager.SaveScene(scene, ReviewScenePath)) throw new IOException("Could not save flat contact review.");
        Debug.Log("FLY_GROUNDED_FLAT_REVIEW_CREATED");
    }

    public static void BuildCandidates()
    {
        Build();
        CreateFlatReview();
        BuildScene(ReviewScenePath, "FlyGroundedContactReview.app");
    }

    public static void BuildFlatReview()
    {
        CreateFlatReview();
        BuildScene(ReviewScenePath, "FlyGroundedContactReview.app");
    }
}
