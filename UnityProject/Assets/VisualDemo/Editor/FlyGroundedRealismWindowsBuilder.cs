using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;

// Windows-only build entry point for the existing grounded realism scene.
// It intentionally does not open, save, or alter the scene or its locomotion assets.
public static class FlyGroundedRealismWindowsBuilder
{
    const string ScenePath = "Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity";

    public static void BuildRuntimeValidation()
    {
        string repo = Path.GetFullPath(Path.Combine(UnityEngine.Application.dataPath, "../.."));
        string player = Path.Combine(repo, "artifacts/windows-runtime-validation/unity/FlyGroundedRealismDemo.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(player));

        BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { ScenePath },
            locationPathName = player,
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.Development
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException("Grounded Windows runtime-validation build failed: " + report.summary.result);
        UnityEngine.Debug.Log("FLY_GROUNDED_WINDOWS_BUILD_PASS " + player);
    }
}
