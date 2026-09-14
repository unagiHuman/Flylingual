using System;
using System.IO;
using System.Linq;
using Flylingual.PlayScreen;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class TitleScreenBuilder
{
    [MenuItem("Flylingual/Title Screen/Create title scene")]
    public static void CreateScene()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        // A batch Editor starts with an untitled scene, which Unity cannot load additively.
        // Interactive use retains the user's current scene and unsaved work.
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,
            Application.isBatchMode ? NewSceneMode.Single : NewSceneMode.Additive);
        try
        {
            var cameraObject = new GameObject("Title Camera");
            SceneManager.MoveGameObjectToScene(cameraObject, scene);
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(.025f, .045f, .075f);
            cameraObject.AddComponent<AudioListener>();
            var title = new GameObject("Title Screen");
            SceneManager.MoveGameObjectToScene(title, scene);
            title.AddComponent<TitleScreen>();
            if (!EditorSceneManager.SaveScene(scene, TitleScreen.ScenePath))
                throw new IOException("Could not save title scene.");
        }
        finally { EditorSceneManager.CloseScene(scene, true); }
        RegisterScenes();
        Debug.Log("TITLE_SCENE_CREATED scene=" + TitleScreen.ScenePath);
    }

    public static string[] BuildScenes()
    {
        if (!File.Exists(TitleScreen.InGameScenePath))
            throw new FileNotFoundException("Create the in-game scene first.", TitleScreen.InGameScenePath);
        if (!File.Exists(TitleScreen.ScenePath)) CreateScene();
        return new[] { TitleScreen.ScenePath, TitleScreen.InGameScenePath };
    }

    public static void RegisterScenes()
    {
        var remaining = EditorBuildSettings.scenes.Where(s => s.path != TitleScreen.ScenePath && s.path != TitleScreen.InGameScenePath);
        EditorBuildSettings.scenes = new[] {
            new EditorBuildSettingsScene(TitleScreen.ScenePath, true),
            new EditorBuildSettingsScene(TitleScreen.InGameScenePath, true)
        }.Concat(remaining).ToArray();
    }
}
