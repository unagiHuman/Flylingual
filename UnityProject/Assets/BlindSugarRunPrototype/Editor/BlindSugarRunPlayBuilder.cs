using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Flylingual.BlindSugarRun;
using Flylingual.Conversation;
using Flylingual.PlayScreen;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>Copies the current native play rig and replaces only its old environment.</summary>
public static class BlindSugarRunPlayBuilder
{
    const string EnvironmentPath = "Assets/BlindSugarRunPrototype/BlindSugarRunEnvironment.prefab";
    static readonly HashSet<string> OldEnvironment = new HashSet<string> {
        "Ground", "Book - field notes", "Book pages", "Book - second volume",
        "First climb - notebook ramp", "Notebook summit", "Narrow ledge",
        "Coffee cup", "Coffee", "Can", "Sugar goal label"
    };

    [MenuItem("Flylingual/Blind Sugar Run/Create startup scene")]
    public static void CreateScene()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        if (EditorSceneManager.GetActiveScene().isDirty) throw new InvalidOperationException("Save the current scene first.");
        if (File.Exists(PlayScreenBuilder.ScenePath))
            throw new InvalidOperationException("Startup scene already exists; edit it in Unity instead of overwriting it.");
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(EnvironmentPath);
        if (prefab == null) throw new InvalidOperationException("Prototype environment prefab is missing.");
        var scene = EditorSceneManager.OpenScene(PlayScreenBuilder.LegacyScenePath);
        var roots = scene.GetRootGameObjects();
        var demo = roots.SelectMany(root => root.GetComponentsInChildren<WindowsReplayDemo>(true)).Single();
        if (demo.body == null || demo.controller == null || demo.live == null || demo.client == null || demo.view == null)
            throw new InvalidOperationException("Existing native Fly integration is incomplete.");
        if (roots.SelectMany(root => root.GetComponentsInChildren<ConversationNativeBootstrap>(true)).Count() != 1 ||
            roots.SelectMany(root => root.GetComponentsInChildren<PlayScreenRuntime>(true)).Count() != 1)
            throw new InvalidOperationException("Expected exactly one existing bootstrap and play UI.");

        // Snapshot every body component: no motor, joint, contact, or rig serialization may change.
        var bodySnapshot = demo.body.GetComponentsInChildren<Component>(true)
            .Where(component => component != null)
            .ToDictionary(component => component, component => EditorJsonUtility.ToJson(component));
        var material = roots.Single(root => root.name == "Ground").GetComponent<Collider>().sharedMaterial;
        var removed = new List<string>();
        foreach (var root in roots)
        {
            bool prop = OldEnvironment.Contains(root.name);
            for (int row = 0; row < 3; row++)
                for (int column = 0; column < 6; column++) prop |= root.name == $"Key {row}-{column}";
            for (int index = 0; index < 32; index++) prop |= root.name == "Goal rim " + index;
            for (int index = 0; index < 3; index++) prop |= root.name == "Sugar crystal " + index;
            if (!prop) continue;
            removed.Add(root.name);
            UnityEngine.Object.DestroyImmediate(root);
        }
        var environment = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
        environment.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        environment.transform.localScale = Vector3.one;
        var geometry = environment.transform.Find("EnvironmentGeometry");
        if (geometry == null) throw new InvalidOperationException("Environment geometry is missing.");
        foreach (var support in geometry.GetComponentsInChildren<Collider>())
        {
            if (support.isTrigger) continue;
            support.sharedMaterial = material;
            if (support.GetComponent<FlyGroundMarker>() == null) support.gameObject.AddComponent<FlyGroundMarker>();
            PrefabUtility.RecordPrefabInstancePropertyModifications(support);
        }
        // The legacy demo goal is unrelated to this stage. Goal stability/reveal is a later phase.
        foreach (var game in roots.Where(root => root != null).SelectMany(root => root.GetComponentsInChildren<AscentGameSession>(true)))
            game.enabled = false;
        var framing = new GameObject("Blind Sugar Run Stage Camera").AddComponent<BlindSugarRunStageCamera>();
        framing.follow = demo.body.transform;
        framing.stageCamera = demo.view;
        demo.view.transform.position = framing.follow.position + framing.offset;
        demo.view.transform.LookAt(framing.follow.position + framing.lookAhead);
        ConfigureGameSession(demo.body, environment);
        ConfigureLocalVisibility(framing);

        foreach (var entry in bodySnapshot)
            if (entry.Key == null || EditorJsonUtility.ToJson(entry.Key) != entry.Value)
                throw new InvalidOperationException("Existing body serialization changed during environment replacement.");
        var start = environment.transform.Find("Anchors/Start");
        if (start == null || Vector3.Distance(demo.body.transform.position, start.position) > .01f)
            throw new InvalidOperationException("Existing Fly does not match the stage start anchor.");
        Physics.SyncTransforms();
        var startFloor = geometry.Find("StartArea").GetComponent<Collider>();
        if (!startFloor.Raycast(new Ray(demo.body.transform.position, Vector3.down), out var hit, 5) || Mathf.Abs(hit.point.y) > .01f)
            throw new InvalidOperationException("Start floor does not support the initial Fly position.");
        if (!EditorSceneManager.SaveScene(scene, PlayScreenBuilder.ScenePath))
            throw new InvalidOperationException("Could not save the startup scene.");
        TitleScreenBuilder.RegisterScenes();
        AssetDatabase.SaveAssets();
        Debug.Log("BLIND_SUGAR_STARTUP_SCENE_PASS scene=" + PlayScreenBuilder.ScenePath +
            " preservedBodyComponents=" + bodySnapshot.Count + " removedEnvironmentRoots=" + removed.Count +
            " start=" + demo.body.transform.position + " floorY=" + hit.point.y + " oldGoalDisabled=true");
    }

    public static void CreateAndBuild()
    {
        CreateScene();
        PlayScreenBuilder.Build();
    }

    static void ConfigureLocalVisibility(BlindSugarRunStageCamera framing)
    {
        var visibility = framing.GetComponent<BlindSugarRunLocalVisibility>();
        if (visibility == null) visibility = framing.gameObject.AddComponent<BlindSugarRunLocalVisibility>();
        visibility.follow = framing.follow;
        visibility.stageCamera = framing.stageCamera;
        var exploration = framing.GetComponent<BlindSugarRunExplorationMap>();
        if (exploration == null) exploration = framing.gameObject.AddComponent<BlindSugarRunExplorationMap>();
        exploration.stage = UnityEngine.Object.FindAnyObjectByType<BlindSugarRunSession>();
        exploration.visibility = visibility;
        if (visibility.spotlight == null)
        {
            var lightObject = new GameObject("Fly Local Spotlight");
            lightObject.transform.SetParent(framing.transform, false);
            visibility.spotlight = lightObject.AddComponent<Light>();
            visibility.spotlight.type = LightType.Spot;
            visibility.spotlight.enabled = false;
        }
    }

    [MenuItem("Flylingual/Blind Sugar Run/Install local spotlight view")]
    public static void InstallLocalVisibility()
    {
        if (EditorApplication.isPlaying || EditorSceneManager.GetActiveScene().isDirty)
            throw new InvalidOperationException("Stop Play Mode and save the scene first.");
        var scene = EditorSceneManager.OpenScene(PlayScreenBuilder.ScenePath);
        var framing = UnityEngine.Object.FindAnyObjectByType<BlindSugarRunStageCamera>();
        if (framing == null) throw new InvalidOperationException("Stage camera missing.");
        ConfigureLocalVisibility(framing);
        if (!EditorSceneManager.SaveScene(scene)) throw new IOException("Could not save local visibility.");
        Debug.Log("BLIND_SUGAR_LOCAL_VIEW_INSTALLED radius=3");
    }

    static void ConfigureGameSession(FlyBody body, GameObject environment)
    {
        var session = UnityEngine.Object.FindFirstObjectByType<BlindSugarRunSession>();
        if (session == null) session = new GameObject("Blind Sugar Run Game Session").AddComponent<BlindSugarRunSession>();
        session.fly = body;
        session.killVolume = environment.transform.Find("Volumes/KillVolume").GetComponent<BoxCollider>();
        session.fallHeight = -2f;
        if (session.GetComponent<BlindSugarRunIdleSwatter>() == null)
            session.gameObject.AddComponent<BlindSugarRunIdleSwatter>();
    }

    [MenuItem("Flylingual/Blind Sugar Run/Install game over and retry")]
    public static void InstallGameOver()
    {
        if (EditorApplication.isPlaying || EditorSceneManager.GetActiveScene().isDirty)
            throw new InvalidOperationException("Stop Play Mode and save the scene first.");
        var scene = EditorSceneManager.OpenScene(PlayScreenBuilder.ScenePath);
        var demo = UnityEngine.Object.FindFirstObjectByType<WindowsReplayDemo>();
        var environment = scene.GetRootGameObjects().Single(root => root.name == "BlindSugarRunEnvironment");
        ConfigureGameSession(demo.body, environment);
        if (!EditorSceneManager.SaveScene(scene)) throw new IOException("Could not save game over integration.");
        Debug.Log("BLIND_SUGAR_GAME_OVER_INSTALLED threshold=-2 retry=scene_reload_with_adapter_rebind");
    }
}
