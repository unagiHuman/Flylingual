using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Pool;
using UnityEngine.SceneManagement;

namespace Flylingual.Effects
{
    /// <summary>Bounded per-kind particle pools. Active instances never cross scene unloads.</summary>
    [DisallowMultipleComponent]
    public sealed class EffectManager : MonoBehaviour
    {
        [Serializable]
        public sealed class EffectDefinition
        {
            public string id;
            public PooledParticleEffect prefab;
            [Min(0)] public int initialCapacity = 4;
            [Min(1)] public int maxInstances = 16;
            [Min(.01f)] public float maxLifetime = 10f;
        }

        sealed class Bucket
        {
            public ObjectPool<PooledParticleEffect> pool;
            public readonly HashSet<PooledParticleEffect> active = new HashSet<PooledParticleEffect>();
            public int limit;
            public float lifetime;
        }

        public static EffectManager Instance { get; private set; }
        public List<EffectDefinition> effects = new List<EffectDefinition>();
        readonly Dictionary<string, Bucket> buckets = new Dictionary<string, Bucket>(StringComparer.Ordinal);
        readonly Dictionary<PooledParticleEffect, Bucket> owners = new Dictionary<PooledParticleEffect, Bucket>();
        Transform poolRoot;
        bool disposing;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            if (Instance != null) SceneManager.sceneUnloaded -= Instance.OnSceneUnloaded;
            Instance = null;
        }

        void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(this); return; }
            Instance = this;
            if (transform.parent != null) transform.SetParent(null, true);
            DontDestroyOnLoad(gameObject);
            var root = new GameObject("Inactive Particle Pool");
            root.transform.SetParent(transform, false);
            root.SetActive(false);
            poolRoot = root.transform;
            if (effects == null) return;
            foreach (var definition in effects)
            {
                if (definition == null || string.IsNullOrWhiteSpace(definition.id) || definition.prefab == null
                    || buckets.ContainsKey(definition.id)) continue;
                var bucket = new Bucket
                {
                    limit = Mathf.Max(1, definition.maxInstances),
                    lifetime = float.IsNaN(definition.maxLifetime) || float.IsInfinity(definition.maxLifetime)
                        ? 10f : Mathf.Max(.01f, definition.maxLifetime)
                };
                int prewarm = Mathf.Clamp(definition.initialCapacity, 0, bucket.limit);
                var prefab = definition.prefab;
                bucket.pool = new ObjectPool<PooledParticleEffect>(
                    () => Create(prefab, bucket), null,
                    effect => { if (effect != null) effect.ReturnToPool(poolRoot); },
                    effect => { if (effect != null) { owners.Remove(effect); effect.DestroyPooled(); } },
                    true, prewarm, bucket.limit);
                buckets.Add(definition.id, bucket);
                var warmed = new List<PooledParticleEffect>(prewarm);
                for (int i = 0; i < prewarm; i++) warmed.Add(bucket.pool.Get());
                foreach (var effect in warmed) bucket.pool.Release(effect);
            }
        }

        PooledParticleEffect Create(PooledParticleEffect prefab, Bucket bucket)
        {
            // The inactive parent prevents play-on-awake before the pooling settings are installed.
            var effect = Instantiate(prefab, poolRoot);
            effect.Initialize(this);
            effect.ReturnToPool(poolRoot);
            owners.Add(effect, bucket);
            return effect;
        }

        void OnEnable()
        {
            if (Instance != this) return;
            SceneManager.sceneUnloaded -= OnSceneUnloaded;
            SceneManager.sceneUnloaded += OnSceneUnloaded;
        }

        public PooledParticleEffect Spawn(string id, Vector3 position) => Spawn(id, position, Quaternion.identity);

        public PooledParticleEffect Spawn(string id, Vector3 position, Quaternion rotation)
        {
            if (Instance != this || !isActiveAndEnabled || disposing || string.IsNullOrEmpty(id)
                || !buckets.TryGetValue(id, out var bucket) || bucket.active.Count >= bucket.limit) return null;
            PooledParticleEffect effect;
            // ObjectPool cannot observe external Destroy of an idle entry; discard destroyed handles.
            do { effect = bucket.pool.Get(); } while (effect == null);
            bucket.active.Add(effect);
            effect.Begin(position, rotation, transform, bucket.lifetime);
            return effect;
        }

        internal void Release(PooledParticleEffect effect)
        {
            if (disposing || effect == null || !owners.TryGetValue(effect, out var bucket)
                || !bucket.active.Remove(effect)) return;
            bucket.pool.Release(effect);
        }

        internal void ForgetDestroyed(PooledParticleEffect effect)
        {
            if (!owners.TryGetValue(effect, out var bucket)) return;
            bucket.active.Remove(effect);
            owners.Remove(effect);
        }

        public void ReleaseAll()
        {
            foreach (var bucket in buckets.Values)
            {
                var active = new List<PooledParticleEffect>(bucket.active);
                foreach (var effect in active)
                {
                    if (effect != null) Release(effect);
                    else bucket.active.Remove(effect);
                }
            }
        }

        void OnSceneUnloaded(Scene scene) => ReleaseAll();

        void OnDisable()
        {
            SceneManager.sceneUnloaded -= OnSceneUnloaded;
            if (Instance == this) ReleaseAll();
        }

        void OnDestroy()
        {
            SceneManager.sceneUnloaded -= OnSceneUnloaded;
            if (Instance != this) return;
            ReleaseAll();
            disposing = true;
            foreach (var bucket in buckets.Values) bucket.pool.Clear();
            buckets.Clear();
            owners.Clear();
            if (poolRoot != null) Destroy(poolRoot.gameObject);
            Instance = null;
        }
    }
}
