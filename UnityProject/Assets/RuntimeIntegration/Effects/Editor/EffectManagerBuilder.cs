using System;
using System.IO;
using Flylingual.Effects;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class EffectManagerBuilder
{
    const string Folder = "Assets/RuntimeIntegration/Effects/Presets";
    public const string PrefabPath = "Assets/RuntimeIntegration/Effects/Resources/FlylingualEffects.prefab";

    [MenuItem("Flylingual/Effects/Create particle effect presets")]
    public static void CreatePresets()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        if (File.Exists(PrefabPath)) { Debug.Log("EFFECT_PRESET_EXISTS path=" + PrefabPath); return; }
        Directory.CreateDirectory(Folder);
        Directory.CreateDirectory(Path.GetDirectoryName(PrefabPath));
        AssetDatabase.Refresh();
        Material material = CreateMaterial();
        string[] ids = { "spark", "confetti", "smoke" };
        var prefabs = new PooledParticleEffect[ids.Length];
        for (int i = 0; i < ids.Length; i++) prefabs[i] = CreateEffect(ids[i], i, material);
        var host = new GameObject("Flylingual Effects");
        try
        {
            var manager = host.AddComponent<EffectManager>();
            var serialized = new SerializedObject(manager);
            var entries = serialized.FindProperty("effects");
            entries.arraySize = ids.Length;
            for (int i = 0; i < ids.Length; i++)
            {
                var entry = entries.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("id").stringValue = ids[i];
                entry.FindPropertyRelative("prefab").objectReferenceValue = prefabs[i];
                entry.FindPropertyRelative("initialCapacity").intValue = 4;
                entry.FindPropertyRelative("maxInstances").intValue = 16;
                entry.FindPropertyRelative("maxLifetime").floatValue = 10f;
            }
            serialized.ApplyModifiedPropertiesWithoutUndo();
            if (PrefabUtility.SaveAsPrefabAsset(host, PrefabPath) == null) throw new IOException("Could not save effect manager.");
            AssetDatabase.SaveAssets();
        }
        finally { UnityEngine.Object.DestroyImmediate(host); }
        Debug.Log("EFFECT_PRESET_CREATED types=spark,confetti,smoke path=" + PrefabPath);
    }

    static Material CreateMaterial()
    {
        string path = Folder + "/SoftParticle.mat";
        var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (existing != null) return existing;
        string texturePath = Folder + "/SoftParticle.asset";
        var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
        if (texture == null)
        {
            texture = new Texture2D(32, 32, TextureFormat.RGBA32, false) { name = "Soft Particle", wrapMode = TextureWrapMode.Clamp };
            for (int y = 0; y < 32; y++)
                for (int x = 0; x < 32; x++)
                {
                    float radius = new Vector2((x - 15.5f) / 15.5f, (y - 15.5f) / 15.5f).magnitude;
                    float alpha = Mathf.Pow(Mathf.Clamp01(1f - radius), 2);
                    texture.SetPixel(x, y, new Color(1, 1, 1, alpha));
                }
            texture.Apply();
            AssetDatabase.CreateAsset(texture, texturePath);
        }
        var shader = Shader.Find("Universal Render Pipeline/Particles/Unlit");
        if (shader == null) throw new InvalidOperationException("URP particle shader is unavailable.");
        var material = new Material(shader) { name = "Soft Particle", renderQueue = (int)RenderQueue.Transparent };
        material.SetTexture("_BaseMap", texture);
        material.SetColor("_BaseColor", Color.white);
        material.SetFloat("_Surface", 1);
        material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
        material.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
        material.SetFloat("_ZWrite", 0);
        material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
        material.SetOverrideTag("RenderType", "Transparent");
        AssetDatabase.CreateAsset(material, path);
        return material;
    }

    static PooledParticleEffect CreateEffect(string id, int kind, Material material)
    {
        string path = Folder + "/" + id + ".prefab";
        var existing = AssetDatabase.LoadAssetAtPath<GameObject>(path);
        if (existing != null) return existing.GetComponent<PooledParticleEffect>();
        var host = new GameObject(id);
        try
        {
            var particles = host.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            var main = particles.main;
            main.playOnAwake = false; main.loop = false; main.duration = 1f;
            main.startLifetime = kind == 2 ? 2.5f : 1.2f;
            main.startSpeed = kind == 2 ? .3f : kind == 1 ? 1.5f : 2f;
            main.startSize = kind == 2 ? .5f : .08f;
            main.gravityModifier = kind == 2 ? -.02f : .25f;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.maxParticles = 64;
            main.startColor = kind == 0 ? new ParticleSystem.MinMaxGradient(new Color(1f, .65f, .1f))
                : kind == 1 ? new ParticleSystem.MinMaxGradient(new Color(.2f, .9f, .8f), new Color(1f, .3f, .65f))
                : new ParticleSystem.MinMaxGradient(new Color(.65f, .7f, .75f, .6f));
            var emission = particles.emission;
            emission.rateOverTime = 0;
            emission.SetBursts(new[] { new ParticleSystem.Burst(0f, (short)(kind == 2 ? 12 : 32)) });
            var shape = particles.shape;
            shape.shapeType = ParticleSystemShapeType.Sphere; shape.radius = .08f;
            var fade = particles.colorOverLifetime; fade.enabled = true;
            var gradient = new Gradient();
            gradient.SetKeys(new[] { new GradientColorKey(Color.white, 0), new GradientColorKey(Color.white, 1) },
                new[] { new GradientAlphaKey(1, 0), new GradientAlphaKey(0, 1) });
            fade.color = gradient;
            var size = particles.sizeOverLifetime; size.enabled = true;
            size.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0, 1, 1, kind == 2 ? 3 : .2f));
            host.GetComponent<ParticleSystemRenderer>().sharedMaterial = material;
            host.AddComponent<PooledParticleEffect>();
            var prefab = PrefabUtility.SaveAsPrefabAsset(host, path);
            if (prefab == null) throw new IOException("Could not save particle prefab: " + id);
            return prefab.GetComponent<PooledParticleEffect>();
        }
        finally { UnityEngine.Object.DestroyImmediate(host); }
    }
}
