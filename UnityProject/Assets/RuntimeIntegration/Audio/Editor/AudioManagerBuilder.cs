using System;
using System.IO;
using Flylingual.Audio;
using Flylingual.PlayScreen;
using UnityEditor;
using UnityEngine;

public static class AudioManagerBuilder
{
    public const string PrefabPath = "Assets/RuntimeIntegration/Audio/Resources/FlylingualAudioManagers.prefab";

    [MenuItem("Flylingual/Audio/Create audio manager preset")]
    public static void CreatePreset()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        if (File.Exists(PrefabPath))
        {
            Debug.Log("AUDIO_MANAGER_PRESET_EXISTS path=" + PrefabPath);
            return;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(PrefabPath));
        AssetDatabase.Refresh();
        var host = new GameObject("Flylingual Audio Managers");
        try
        {
            var bgm = host.AddComponent<BGMManager>();
            var serializedBgm = new SerializedObject(bgm);
            var scenes = serializedBgm.FindProperty("sceneBGMs");
            scenes.arraySize = 2;
            string[] paths = { TitleScreen.ScenePath, TitleScreen.InGameScenePath };
            for (int i = 0; i < paths.Length; i++)
            {
                var entry = scenes.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("sceneName").stringValue = paths[i];
                entry.FindPropertyRelative("volume").floatValue = 1f;
            }
            serializedBgm.ApplyModifiedPropertiesWithoutUndo();
            var se = host.AddComponent<SEManager>();
            var serializedSe = new SerializedObject(se);
            var entries = serializedSe.FindProperty("entries");
            entries.arraySize = Enum.GetValues(typeof(SEType)).Length;
            for (int i = 0; i < entries.arraySize; i++)
            {
                var entry = entries.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("type").enumValueIndex = i;
                entry.FindPropertyRelative("volume").floatValue = 1f;
                entry.FindPropertyRelative("pitch").floatValue = 1f;
            }
            serializedSe.ApplyModifiedPropertiesWithoutUndo();
            if (PrefabUtility.SaveAsPrefabAsset(host, PrefabPath) == null)
                throw new IOException("Could not save audio manager preset.");
            AssetDatabase.SaveAssets();
        }
        finally { UnityEngine.Object.DestroyImmediate(host); }
        Debug.Log("AUDIO_MANAGER_PRESET_CREATED path=" + PrefabPath + " clips=unassigned");
    }
}
