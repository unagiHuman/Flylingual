using System.Collections.Generic;
using FlyLocomotionPoC;
using FlyBrainPoC;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class FlyLocomotionSandboxBuilder
{
    private const string ScenePath = "Assets/Scenes/FlyLocomotionSandbox.unity";
    private const string ConfigPath = "Assets/FlyLocomotion/FlyLocomotionConfig.asset";

    [MenuItem("FlyBrain PoC/Build Fly Locomotion Sandbox")]
    public static void BuildScene()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        FlyLocomotionConfig config = GetOrCreateConfig();

        CreateGround();
        CreateLighting();
        CreateCamera();

        var flyRoot = GameObject.CreatePrimitive(PrimitiveType.Capsule);
        flyRoot.name = "FlyRoot_Thorax";
        flyRoot.transform.position = new Vector3(0f, 1.45f, 0f);
        flyRoot.transform.localScale = new Vector3(config.thoraxSize.x, config.thoraxSize.y * 0.5f, config.thoraxSize.z);

        var thorax = flyRoot.AddComponent<ArticulationBody>();
        thorax.jointType = ArticulationJointType.FixedJoint;
        thorax.immovable = false;
        thorax.mass = config.thoraxMass;
        thorax.linearDamping = config.thoraxLinearDamping;
        thorax.angularDamping = config.thoraxAngularDamping;

        var flyBody = flyRoot.AddComponent<FlyBody>();
        var mockObject = new GameObject("MockMotorSource");
        var mock = mockObject.AddComponent<MockMotorSource>();
        mock.SetStraight();

        var brainObject = new GameObject("BrainIntegration_Optional");
        var brainClient = brainObject.AddComponent<BrainTcpClient>();
        brainClient.enabled = false;
        var brainSource = brainObject.AddComponent<BrainMotorSource>();
        brainSource.Configure(brainClient);
        brainSource.enabled = false;

        var legs = new List<FlyLeg>();
        CreateLeg(flyRoot.transform, config, legs, "LF", true, FlyLeg.TripodGroup.A, 0.72f, -1f);
        CreateLeg(flyRoot.transform, config, legs, "LM", true, FlyLeg.TripodGroup.B, 0f, -1f);
        CreateLeg(flyRoot.transform, config, legs, "LH", true, FlyLeg.TripodGroup.A, -0.72f, -1f);
        CreateLeg(flyRoot.transform, config, legs, "RF", false, FlyLeg.TripodGroup.B, 0.72f, 1f);
        CreateLeg(flyRoot.transform, config, legs, "RM", false, FlyLeg.TripodGroup.A, 0f, 1f);
        CreateLeg(flyRoot.transform, config, legs, "RH", false, FlyLeg.TripodGroup.B, -0.72f, 1f);

        flyBody.Configure(thorax, config, legs.ToArray());
        var controller = flyRoot.AddComponent<FlyLocomotionController>();
        controller.Configure(flyBody, mock, config);
        var diagnostics = flyRoot.AddComponent<FlyLocomotionDiagnostics>();
        diagnostics.Configure(flyBody, controller, mock, brainSource, brainClient, config.statusLogIntervalSeconds);
        var characterization = flyRoot.AddComponent<FlyActionCharacterization>();
        characterization.Configure(flyBody, controller, brainSource, brainClient);

        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[]
        {
            new EditorBuildSettingsScene(ScenePath, true)
        };
        AssetDatabase.SaveAssets();
        Debug.Log("Fly locomotion sandbox built: " + ScenePath + " joints=18 source=MockMotorSource");
    }

    public static void BuildPlayer()
    {
        string outputPath = GetArgument("-buildOutput");
        if (string.IsNullOrEmpty(outputPath))
        {
            outputPath = "Build/FlyLocomotionSandbox.app";
        }

        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { ScenePath },
            locationPathName = outputPath,
            target = BuildTarget.StandaloneOSX,
            options = BuildOptions.None
        });

        if (report.summary.result != BuildResult.Succeeded)
        {
            throw new System.Exception("Fly locomotion sandbox build failed: " + report.summary.result);
        }

        Debug.Log("Fly locomotion sandbox player built: " + outputPath);
    }

    private static string GetArgument(string name)
    {
        string[] arguments = System.Environment.GetCommandLineArgs();
        for (int i = 0; i < arguments.Length - 1; i++)
        {
            if (arguments[i] == name)
            {
                return arguments[i + 1];
            }
        }

        return string.Empty;
    }

    private static FlyLocomotionConfig GetOrCreateConfig()
    {
        FlyLocomotionConfig config = AssetDatabase.LoadAssetAtPath<FlyLocomotionConfig>(ConfigPath);
        if (config != null)
        {
            return config;
        }

        config = ScriptableObject.CreateInstance<FlyLocomotionConfig>();
        AssetDatabase.CreateAsset(config, ConfigPath);
        AssetDatabase.SaveAssets();
        return config;
    }

    private static void CreateGround()
    {
        var ground = GameObject.CreatePrimitive(PrimitiveType.Cube);
        ground.name = "Ground";
        ground.AddComponent<FlyGroundMarker>();
        ground.transform.position = new Vector3(0f, -0.05f, 0f);
        ground.transform.localScale = new Vector3(30f, 0.1f, 30f);
    }

    private static void CreateLighting()
    {
        var lightObject = new GameObject("Directional Light");
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.2f;
        lightObject.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
    }

    private static void CreateCamera()
    {
        var cameraObject = new GameObject("Main Camera");
        var camera = cameraObject.AddComponent<Camera>();
        cameraObject.tag = "MainCamera";
        cameraObject.transform.position = new Vector3(0f, 5.5f, -8.5f);
        cameraObject.transform.rotation = Quaternion.Euler(27f, 0f, 0f);
        camera.fieldOfView = 60f;
    }

    private static void CreateLeg(Transform thorax, FlyLocomotionConfig config, List<FlyLeg> legs, string id, bool left, FlyLeg.TripodGroup group, float z, float side)
    {
        Vector3 coxaPosition = new Vector3(0.68f * side, -0.24f, z);
        // Revolute ArticulationBody drives rotate around the segment local X axis.
        // Use a basis whose local X points vertically so Coxa target angles sweep
        // the foot in the forward/backward plane instead of only changing height.
        Quaternion coxaRotation = Quaternion.LookRotation(new Vector3(side, 0f, 0f), Vector3.forward);
        FlyJoint coxa = CreateJointSegment(id + "_Coxa", thorax, coxaPosition, coxaRotation, config.coxaLength, config.coxaRadius, config, coxaPosition);

        // Coxa local X is vertical with opposite sign on the two sides.  Mirror
        // the local direction so both Femur chains point down in world space.
        Vector3 femurDirection = new Vector3(-0.95f * side, 0.30f, 0f).normalized;
        Quaternion femurRotation = Quaternion.FromToRotation(Vector3.forward, femurDirection);
        Vector3 femurPosition = new Vector3(0f, 0f, config.coxaLength);
        FlyJoint femur = CreateJointSegment(id + "_Femur", coxa.transform, femurPosition, femurRotation, config.femurLength, config.femurRadius, config, femurPosition);

        Vector3 tibiaDirection = new Vector3(-0.98f * side, 0.20f, 0f).normalized;
        Quaternion tibiaRotation = Quaternion.FromToRotation(Vector3.forward, tibiaDirection);
        Vector3 tibiaPosition = new Vector3(0f, 0f, config.femurLength);
        FlyJoint tibia = CreateJointSegment(id + "_Tibia", femur.transform, tibiaPosition, tibiaRotation, config.tibiaLength, config.tibiaRadius, config, tibiaPosition);
        var footPad = new GameObject(id + "_FootPad");
        footPad.transform.SetParent(tibia.transform, false);
        footPad.transform.localPosition = Vector3.forward * (config.tibiaLength + config.tibiaRadius * 0.75f);
        var footCollider = footPad.AddComponent<SphereCollider>();
        footCollider.radius = config.tibiaRadius * 0.65f;
        footCollider.isTrigger = false;
        var contact = footPad.AddComponent<FlyFootContact>();
        ArticulationBody tibiaBody = tibia.GetComponent<ArticulationBody>();
        contact.Configure(id, footCollider, tibiaBody);
        var collisionRelay = tibia.gameObject.AddComponent<FlyFootPadCollisionRelay>();
        collisionRelay.Configure(contact);
        var adhesion = tibia.gameObject.AddComponent<FlyFootAdhesion>();
        adhesion.Configure(tibiaBody, contact);

        var leg = coxa.gameObject.AddComponent<FlyLeg>();
        leg.Configure(id, left, group, coxa, femur, tibia, contact, adhesion);
        legs.Add(leg);
    }

    private static FlyJoint CreateJointSegment(string name, Transform parent, Vector3 localPosition, Quaternion localRotation, float length, float radius, FlyLocomotionConfig config, Vector3 parentAnchor)
    {
        var segment = new GameObject(name);
        segment.transform.SetParent(parent, false);
        segment.transform.localPosition = localPosition;
        segment.transform.localRotation = localRotation;

        var articulation = segment.AddComponent<ArticulationBody>();
        var collider = segment.AddComponent<CapsuleCollider>();
        collider.direction = 2;
        collider.radius = radius;
        collider.height = length + radius * 2f;
        collider.center = Vector3.forward * (length * 0.5f);

        var visual = GameObject.CreatePrimitive(PrimitiveType.Capsule);
        visual.name = name + "_Visual";
        visual.transform.SetParent(segment.transform, false);
        visual.transform.localPosition = Vector3.forward * (length * 0.5f);
        visual.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
        visual.transform.localScale = new Vector3(radius * 2f, length * 0.5f, radius * 2f);
        Object.DestroyImmediate(visual.GetComponent<Collider>());

        var joint = segment.AddComponent<FlyJoint>();
        joint.Configure(articulation, config, parentAnchor);
        return joint;
    }
}
