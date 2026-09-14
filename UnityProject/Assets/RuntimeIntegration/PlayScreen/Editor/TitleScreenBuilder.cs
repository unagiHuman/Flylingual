using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class TitleScreenBuilder
{
    [InitializeOnLoadMethod]
    static void ConfigurePrototypeStartup()
    {
        EditorApplication.delayCall += () =>
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode || !File.Exists(PlayScreenBuilder.ScenePath)) return;
            var scenes = EditorBuildSettings.scenes;
            if (scenes.Length != 1 || scenes[0].path != PlayScreenBuilder.ScenePath || !scenes[0].enabled)
                RegisterScenes();
            UnityEditor.SceneManagement.EditorSceneManager.playModeStartScene =
                AssetDatabase.LoadAssetAtPath<SceneAsset>(PlayScreenBuilder.ScenePath);
        };
    }

    // Keep the entry point for existing build automation. The title is now a runtime overlay.
    [MenuItem("Flylingual/Title Screen/Configure single-scene startup")]
    public static void CreateScene()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        RegisterScenes();
        Debug.Log("SINGLE_SCENE_STARTUP_CONFIGURED scene=" + PlayScreenBuilder.ScenePath);
    }

    public static string[] BuildScenes()
    {
        if (!File.Exists(PlayScreenBuilder.ScenePath))
            throw new FileNotFoundException("Create the in-game scene first.", PlayScreenBuilder.ScenePath);
        return new[] { PlayScreenBuilder.ScenePath };
    }

    public static void RegisterScenes()
    {
        BuildScenes();
        EditorBuildSettings.scenes = new[] {
            new EditorBuildSettingsScene(PlayScreenBuilder.ScenePath, true)
        };
    }
}
