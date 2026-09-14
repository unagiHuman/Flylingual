using UnityEngine;

namespace Flylingual.Effects
{
    public static class EffectManagerBootstrap
    {
        public const string ResourcePath = "FlylingualEffects";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Install()
        {
            if (EffectManager.Instance != null) return;
            var prefab = Resources.Load<GameObject>(ResourcePath);
            if (prefab != null) Object.Instantiate(prefab).name = "Flylingual Effects";
            else new GameObject("Flylingual Effects").AddComponent<EffectManager>();
        }
    }
}
