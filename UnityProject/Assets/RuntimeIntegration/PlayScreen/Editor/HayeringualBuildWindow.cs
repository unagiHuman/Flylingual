using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public enum HayeringualBuildChannel { Dev, Demo, Judge }
public enum HayeringualLlmProvider { Local, Cloud }

public sealed class HayeringualBuildWindow : EditorWindow
{
    private HayeringualBuildChannel channel;
    private HayeringualLlmProvider provider;
    private string backendUrl = "https://example.vercel.app/api/fly/translate";

    [MenuItem("Flylingual/Build Channels/Configure Windows Build")]
    public static void Open() => GetWindow<HayeringualBuildWindow>("Hayeringual Build");

    // Batch entry point uses the same settings as the submitted Windows edition.
    public static void BuildSubmission() => Build(HayeringualBuildChannel.Judge,
        HayeringualLlmProvider.Cloud, "https://hayeringual-api.vercel.app/api/fly/translate");

    private void OnGUI()
    {
        var selected = (HayeringualBuildChannel)EditorGUILayout.EnumPopup("Channel", channel);
        if (selected != channel)
        {
            channel = selected;
            provider = channel == HayeringualBuildChannel.Judge ? HayeringualLlmProvider.Cloud : HayeringualLlmProvider.Local;
        }
        provider = (HayeringualLlmProvider)EditorGUILayout.EnumPopup("LLM provider", provider);
        if (provider == HayeringualLlmProvider.Cloud) backendUrl = EditorGUILayout.TextField("Application backend", backendUrl);
        EditorGUILayout.HelpBox("Dev includes debugging. Provider is independent. Cloud builds require package_judge.py with a portable Python runtime before distribution.", MessageType.Info);
        if (GUILayout.Button("Build Windows Player")) Build(channel, provider, backendUrl);
    }

    public static string Build(HayeringualBuildChannel channel, HayeringualLlmProvider provider, string backendUrl = "")
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode before building.");
        if (provider == HayeringualLlmProvider.Cloud &&
            (!Uri.TryCreate(backendUrl, UriKind.Absolute, out var uri) || uri.Scheme != "https" ||
             uri.Host == "ai-gateway.vercel.sh" || !String.IsNullOrEmpty(uri.UserInfo) ||
             !String.IsNullOrEmpty(uri.Query) || !String.IsNullOrEmpty(uri.Fragment)))
            throw new ArgumentException("An HTTPS application backend URL without credentials is required.");
        string root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
        string output = Path.Combine(root, "artifacts", "hayeringual-builds", channel + "-" + provider);
        Directory.CreateDirectory(output);
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = TitleScreenBuilder.BuildScenes(),
            locationPathName = Path.Combine(output, "FlylingualConversation.exe"),
            target = BuildTarget.StandaloneWindows64,
            extraScriptingDefines = new[] { "FLY_NATIVE_CONVERSATION" },
            options = channel == HayeringualBuildChannel.Dev ? BuildOptions.Development : BuildOptions.None
        });
        if (report.summary.result != BuildResult.Succeeded) throw new InvalidOperationException("Build failed: " + report.summary.result);
        File.WriteAllText(Path.Combine(output, "build-channel.json"), JsonUtility.ToJson(new BuildSelection {
            channel = channel.ToString(), provider = provider.ToString(), backendUrl = backendUrl
        }, true));
        Debug.Log("HAYERINGUAL_BUILD_PASS " + output);
        return output;
    }

    [Serializable]
    private sealed class BuildSelection { public string channel; public string provider; public string backendUrl; }
}
