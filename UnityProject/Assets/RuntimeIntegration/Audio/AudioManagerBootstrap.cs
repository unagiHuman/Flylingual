using UnityEngine;

namespace Flylingual.Audio
{
    public static class AudioManagerBootstrap
    {
        public const string ResourcePath = "FlylingualAudioManagers";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Install()
        {
            if (BGMManager.Instance != null && SEManager.Instance != null) return;
            var prefab = Resources.Load<GameObject>(ResourcePath);
            if (prefab != null)
            {
                Object.Instantiate(prefab).name = "Flylingual Audio Managers";
                return;
            }
            // Keep direct scene play usable even before the optional clip preset is created.
            var host = new GameObject("Flylingual Audio Managers");
            if (BGMManager.Instance == null) host.AddComponent<BGMManager>();
            if (SEManager.Instance == null) host.AddComponent<SEManager>();
        }
    }
}
