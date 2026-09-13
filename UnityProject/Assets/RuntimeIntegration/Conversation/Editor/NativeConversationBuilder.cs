using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using Flylingual.Conversation;

public static class NativeConversationBuilder
{
    public const string TestScene = "Assets/RuntimeIntegration/Conversation/NativeConversationTest.unity";

    [MenuItem("Flylingual/Conversation/Create independent test scene")]
    public static void CreateTestScene()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var camera = new GameObject("Camera").AddComponent<Camera>();
        camera.backgroundColor = new Color(.04f, .08f, .1f);
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.gameObject.AddComponent<AudioListener>();
        new GameObject("Conversation Services").AddComponent<ConversationNativeBootstrap>();
        EditorSceneManager.SaveScene(scene, TestScene);
    }

    [MenuItem("Flylingual/Conversation/Build Windows conversation Player")]
    public static void Build()
    {
        string root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
        string player = Path.Combine(root, "artifacts/windows-native-conversation/unity/FlylingualConversation.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(player));
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = new[] { PlayScreenBuilder.ScenePath },
            locationPathName = player, target = BuildTarget.StandaloneWindows64,
            extraScriptingDefines = new[] { "FLY_NATIVE_CONVERSATION" },
            options = BuildOptions.Development
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException("Native conversation build failed: " + report.summary.result);
        Debug.Log("NATIVE_CONVERSATION_BUILD_PASS");
    }

    [MenuItem("Flylingual/Conversation/Build Mac conversation Player")]
    public static void BuildMac()
    {
        string root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
        string player = Path.Combine(root, "artifacts/mac-native-conversation/unity/FlylingualConversation.app");
        Directory.CreateDirectory(Path.GetDirectoryName(player));
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = new[] { "Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity" },
            locationPathName = player, target = BuildTarget.StandaloneOSX,
            extraScriptingDefines = new[] { "FLY_NATIVE_CONVERSATION" },
            options = BuildOptions.Development
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException("Mac native conversation build failed: " + report.summary.result);
        Debug.Log("NATIVE_MAC_CONVERSATION_BUILD_PASS");
    }
}
