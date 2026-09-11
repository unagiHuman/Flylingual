using FlyBrainPoC;
using FlyLocomotionPoC;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class FlyStepObstacleSandboxBuilder
{
    private const string BaseScenePath = "Assets/Scenes/FlyLocomotionSandbox.unity";
    private const string StepScenePath = "Assets/Scenes/FlyStepObstacleSandbox.unity";

    [MenuItem("FlyBrain PoC/Build Fly Step Obstacle Sandbox")]
    public static void BuildScene()
    {
        Scene scene = EditorSceneManager.OpenScene(BaseScenePath, OpenSceneMode.Single);
        GameObject flyRoot = GameObject.Find("FlyRoot_Thorax");
        if (flyRoot == null)
        {
            throw new System.InvalidOperationException("FlyRoot_Thorax was not found in the flat baseline scene.");
        }

        GameObject oldObstacle = GameObject.Find("StepObstacle");
        if (oldObstacle != null)
        {
            Object.DestroyImmediate(oldObstacle);
        }

        GameObject oldPlatform = GameObject.Find("UpperPlatform");
        if (oldPlatform != null)
        {
            Object.DestroyImmediate(oldPlatform);
        }

        GameObject upperPlatform = GameObject.CreatePrimitive(PrimitiveType.Cube);
        upperPlatform.name = "UpperPlatform";
        upperPlatform.AddComponent<FlyGroundMarker>();

        GameObject stepObject = GameObject.CreatePrimitive(PrimitiveType.Cube);
        stepObject.name = "StepObstacle";
        FlyStepObstacle step = stepObject.AddComponent<FlyStepObstacle>();
        step.Configure(0.02f, 1.8f, 0.8f, 8f, upperPlatform.transform, 8f);

        FlyBody flyBody = flyRoot.GetComponent<FlyBody>();
        FlyLocomotionController controller = flyRoot.GetComponent<FlyLocomotionController>();
        MockMotorSource mock = GameObject.Find("MockMotorSource")?.GetComponent<MockMotorSource>();
        GameObject brainObject = GameObject.Find("BrainIntegration_Optional");
        BrainTcpClient brainClient = brainObject == null ? null : brainObject.GetComponent<BrainTcpClient>();
        BrainMotorSource brainSource = brainObject == null ? null : brainObject.GetComponent<BrainMotorSource>();
        var replaySource = flyRoot.GetComponent<ReplayMotorSource>() ?? flyRoot.AddComponent<ReplayMotorSource>();
        var reflexLayer = flyRoot.GetComponent<FlyLocalReflexLayer>() ?? flyRoot.AddComponent<FlyLocalReflexLayer>();
        reflexLayer.Configure(flyBody, step);
        reflexLayer.ConfigureMode("NONE");
        reflexLayer.enabled = false;
        controller.SetReflexLayer(reflexLayer);
        var kinematicsDiagnostics = flyRoot.GetComponent<FlyStepKinematicsDiagnostics>() ?? flyRoot.AddComponent<FlyStepKinematicsDiagnostics>();
        kinematicsDiagnostics.Configure(flyBody, controller, step);
        var characterization = flyRoot.GetComponent<FlyStepObstacleCharacterization>() ?? flyRoot.AddComponent<FlyStepObstacleCharacterization>();
        characterization.Configure(flyBody, controller, mock, brainSource, brainClient, replaySource, step, reflexLayer, kinematicsDiagnostics);
        var visualDiagnostics = flyRoot.GetComponent<FlyStepVisualDiagnostics>() ?? flyRoot.AddComponent<FlyStepVisualDiagnostics>();
        visualDiagnostics.Configure(flyBody, controller, step, reflexLayer);

        EditorSceneManager.SaveScene(scene, StepScenePath);
        AssetDatabase.SaveAssets();
        Debug.Log("Fly step obstacle sandbox built: " + StepScenePath + " defaultHeight=0.02m baseline=unchanged");
    }

    public static void BuildPlayer()
    {
        string outputPath = GetArgument("-buildOutput");
        if (string.IsNullOrEmpty(outputPath))
        {
            outputPath = "Build/FlyStepObstacleSandbox.app";
        }

        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { StepScenePath },
            locationPathName = outputPath,
            target = BuildTarget.StandaloneOSX,
            options = BuildOptions.None
        });

        if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
        {
            throw new System.Exception("Fly step obstacle sandbox build failed: " + report.summary.result);
        }

        Debug.Log("Fly step obstacle sandbox player built: " + outputPath);
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
}
