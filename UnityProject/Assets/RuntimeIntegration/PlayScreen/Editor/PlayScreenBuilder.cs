using System;
using System.IO;
using Flylingual.Conversation;
using Flylingual.PlayScreen;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class PlayScreenBuilder
{
    public const string ScenePath = "Assets/RuntimeIntegration/PlayScreen/FlylingualPlay.unity";

    [MenuItem("Flylingual/Play Screen/Create formal play scene")]
    public static void CreateScene()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        if (EditorSceneManager.GetActiveScene().isDirty) throw new InvalidOperationException("Save the current scene before creating the play scene.");
        var scene = EditorSceneManager.OpenScene("Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity");
        var services = new GameObject("Flylingual Play Services");
        services.AddComponent<ConversationNativeBootstrap>();
        var presentation = new GameObject("Flylingual Play Screen").AddComponent<PlayScreenRuntime>();
        presentation.neuralShader = AssetDatabase.LoadAssetAtPath<Shader>("Assets/BrainVisualization/Rendering/NeuralPointCloud.shader");
        EditorSceneManager.SaveScene(scene, ScenePath);
        Debug.Log("PLAY_SCREEN_SCENE_SAVED " + ScenePath);
    }

    [MenuItem("Flylingual/Play Screen/Build Windows Player")]
    public static void Build()
    {
        const string settingsPath = "Assets/RuntimeIntegration/PlayScreen/Resources/PlayScreenPanelSettings.asset";
        if (AssetDatabase.LoadAssetAtPath<UnityEngine.UIElements.PanelSettings>(settingsPath) == null)
        {
            var settings = ScriptableObject.CreateInstance<UnityEngine.UIElements.PanelSettings>();
            settings.themeStyleSheet = Resources.Load<UnityEngine.UIElements.ThemeStyleSheet>("PlayScreenTheme");
            AssetDatabase.CreateAsset(settings, settingsPath);
            AssetDatabase.SaveAssets();
        }
        string root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
        string player = Path.Combine(root, "artifacts/windows-native-conversation/unity/FlylingualConversation.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(player));
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = new[] { ScenePath }, locationPathName = player, target = BuildTarget.StandaloneWindows64,
            extraScriptingDefines = new[] { "FLY_NATIVE_CONVERSATION" }, options = BuildOptions.Development
        });
        if (report.summary.result != BuildResult.Succeeded) throw new InvalidOperationException("Play screen build failed: " + report.summary.result);
        Debug.Log("PLAY_SCREEN_BUILD_PASS");
    }
}
