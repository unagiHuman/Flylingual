using System;
using System.IO;
using FlyLocomotionPoC;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class FlyTerrainDemoBuilder
{
    const string Folder = "Assets/VisualDemo/TerrainDemo";
    static string Output => Path.GetFullPath(Path.Combine(Application.dataPath, "../../artifacts/terrain-sensing"));
    [MenuItem("FlyBrain/Terrain/Create independent terrain scenes")]
    public static void Create()
    {
        if (EditorSceneManager.GetActiveScene().isDirty) throw new InvalidOperationException("Save the current scene first.");
        Directory.CreateDirectory(Folder);
        foreach (string variant in new[] { "Flat", "Step", "StepTall", "Wall", "Edge" })
        {
            var scene = EditorSceneManager.OpenScene(FlyGroundedRealismBuilder.ReviewScenePath);
            var floor = GameObject.Find("Ground");
            floor.transform.position = new Vector3(0, -.1f, 0);
            floor.transform.localScale = new Vector3(20, .2f, 40);
            if (variant == "Step") MakeBox("Terrain Step", new Vector3(0, .09f, 7.4f), new Vector3(12, .18f, 10));
            if (variant == "StepTall") MakeBox("Terrain Taller Step", new Vector3(0, .15f, 7.4f), new Vector3(12, .30f, 10));
            if (variant == "Wall") MakeBox("Terrain Wall", new Vector3(0, 1.5f, 2.9f), new Vector3(12, 3, 1));
            if (variant == "Edge") { floor.transform.position = new Vector3(0, -.1f, -7.4f); floor.transform.localScale = new Vector3(20, .2f, 20); }
            if (!EditorSceneManager.SaveScene(scene, Folder + "/FlyTerrain" + variant + ".unity")) throw new IOException("Could not save terrain scene.");
        }
        AssetDatabase.Refresh();
        Debug.Log("FLY_TERRAIN_SCENES_CREATED");
    }
    static void MakeBox(string name, Vector3 position, Vector3 size)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube); go.name = name;
        go.transform.position = position; go.transform.localScale = size;
        go.AddComponent<FlyGroundMarker>();
    }
    [MenuItem("FlyBrain/Terrain/Build Mac terrain Players")]
    public static void Build()
    {
        Directory.CreateDirectory(Output);
        foreach (string variant in new[] { "Flat", "Step", "StepTall", "Wall", "Edge" })
        {
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
                scenes = new[] { Folder + "/FlyTerrain" + variant + ".unity" },
                target = BuildTarget.StandaloneOSX, options = BuildOptions.Development,
                locationPathName = Path.Combine(Output, "FlyTerrain" + variant + ".app")
            });
            if (report.summary.result != BuildResult.Succeeded) throw new InvalidOperationException("Terrain build failed: " + variant);
        }
        Debug.Log("FLY_TERRAIN_BUILD_PASS");
    }
    public static void CreateAndBuild() { Create(); Build(); }
}
