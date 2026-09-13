// Execute this body with Unity CLI eval. Creates only an isolated test scene/Player.
if (UnityEditor.EditorApplication.isPlaying || UnityEditor.BuildPipeline.isBuildingPlayer)
    throw new System.InvalidOperationException("Editor is busy");
string destination = "Assets/RuntimeIntegration/Conversation/PersistentVoiceFlat.unity";
if (System.IO.File.Exists(destination))
    throw new System.InvalidOperationException("Test scene already exists; do not overwrite it");
var source = PlayScreenBuilder.LegacyScenePath;
var before = System.IO.File.ReadAllBytes(source);
var previousScene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
var scene = UnityEditor.SceneManagement.EditorSceneManager.OpenScene(source, UnityEditor.SceneManagement.OpenSceneMode.Additive);
try
{
    var keep = new System.Collections.Generic.HashSet<string> {
        "Ground", "Directional Light", "Main Camera", "FlyRoot_Thorax", "MockMotorSource",
        "BrainIntegration_Optional", "WindowsReplayDemo", "VisualRig", "Cool rim",
        "Flylingual Play Services", "Flylingual Play Screen"
    };
    UnityEngine.GameObject ground = null;
    foreach (var rootObject in scene.GetRootGameObjects())
    {
        if (rootObject.name == "Ground") ground = rootObject;
        if (!keep.Contains(rootObject.name)) UnityEngine.Object.DestroyImmediate(rootObject);
    }
    if (ground == null) throw new System.InvalidOperationException("Existing ground missing");
    ground.transform.position = new UnityEngine.Vector3(0, -.1f, 0);
    ground.transform.localScale = new UnityEngine.Vector3(1000, .2f, 1000);
    if (!UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, destination))
        throw new System.IO.IOException("Test scene save failed");
}
finally
{
    UnityEditor.SceneManagement.EditorSceneManager.CloseScene(scene, true);
    UnityEngine.SceneManagement.SceneManager.SetActiveScene(previousScene);
}
if (!System.Linq.Enumerable.SequenceEqual(before, System.IO.File.ReadAllBytes(source)))
    throw new System.InvalidOperationException("Source scene changed");
string output = System.IO.Path.GetFullPath("../artifacts/voice-tests/persistent-flat-player/FlylingualConversation.exe");
System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(output));
var build = UnityEditor.BuildPipeline.BuildPlayer(new UnityEditor.BuildPlayerOptions {
    scenes = new[] { destination }, locationPathName = output,
    target = UnityEditor.BuildTarget.StandaloneWindows64,
    options = UnityEditor.BuildOptions.Development,
    extraScriptingDefines = new[] { "FLY_NATIVE_CONVERSATION" }
});
if (build.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
    throw new System.InvalidOperationException("Persistent flat test build failed");
return "PERSISTENT_FLAT_BUILD_PASS " + output;
