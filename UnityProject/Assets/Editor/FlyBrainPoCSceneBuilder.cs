using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using FlyBrainPoC;

public static class FlyBrainPoCSceneBuilder
{
    private const string ScenePath = "Assets/Scenes/BrainIntegrationPoC.unity";

    [MenuItem("FlyBrain PoC/Build Integration Scene")]
    public static void BuildScene()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        var ground = GameObject.CreatePrimitive(PrimitiveType.Cube);
        ground.name = "Ground";
        ground.transform.position = new Vector3(0f, -0.5f, 0f);
        ground.transform.localScale = new Vector3(20f, 1f, 20f);

        var capsule = GameObject.CreatePrimitive(PrimitiveType.Capsule);
        capsule.name = "Capsule";
        capsule.transform.position = new Vector3(0f, 1f, 0f);
        var body = capsule.AddComponent<Rigidbody>();
        body.mass = 1f;
        body.constraints = RigidbodyConstraints.FreezeRotationX | RigidbodyConstraints.FreezeRotationZ;
        var capsuleController = capsule.AddComponent<BrainDrivenCapsule>();

        var cameraObject = new GameObject("Main Camera");
        var camera = cameraObject.AddComponent<Camera>();
        cameraObject.tag = "MainCamera";
        cameraObject.transform.position = new Vector3(0f, 6f, -10f);
        cameraObject.transform.rotation = Quaternion.Euler(25f, 0f, 0f);
        camera.fieldOfView = 60f;

        var lightObject = new GameObject("Directional Light");
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.2f;
        lightObject.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        var integration = new GameObject("BrainIntegration");
        var client = integration.AddComponent<BrainTcpClient>();
        var panel = integration.AddComponent<BrainControlPanel>();
        capsuleController.Configure(client, body);
        panel.Configure(client);

        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[]
        {
            new EditorBuildSettingsScene(ScenePath, true)
        };
        AssetDatabase.SaveAssets();
        Debug.Log("FlyBrain PoC scene built: " + ScenePath);
    }
}
