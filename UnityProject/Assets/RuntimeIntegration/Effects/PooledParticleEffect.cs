using UnityEngine;

namespace Flylingual.Effects
{
    /// <summary>One particle-system hierarchy leased from EffectManager.</summary>
    [DisallowMultipleComponent]
    [RequireComponent(typeof(ParticleSystem))]
    public sealed class PooledParticleEffect : MonoBehaviour
    {
        ParticleSystem[] particles;
        EffectManager owner;
        float expiresAt;
        Vector3 initialScale;
        public bool IsSpawned { get; private set; }
        public uint Version { get; private set; }

        internal void Initialize(EffectManager manager)
        {
            owner = manager;
            initialScale = transform.localScale;
            enabled = true;
            particles = GetComponentsInChildren<ParticleSystem>(true);
            foreach (var particle in particles)
            {
                var main = particle.main;
                main.playOnAwake = false;
                main.stopAction = ParticleSystemStopAction.None;
            }
            ResetParticles();
        }

        internal void Begin(Vector3 position, Quaternion rotation, Transform activeParent, float lifetime)
        {
            transform.SetParent(activeParent, false);
            transform.SetPositionAndRotation(position, rotation);
            Version++;
            IsSpawned = true;
            expiresAt = Time.unscaledTime + lifetime;
            gameObject.SetActive(true);
            // Start roots only; Play(true) also starts their child particle systems.
            foreach (var particle in particles)
                if (particle != null && !HasParticleParent(particle.transform)) particle.Play(true);
        }

        bool HasParticleParent(Transform child)
        {
            for (var parent = child.parent; parent != null && parent != transform.parent; parent = parent.parent)
                if (parent.GetComponent<ParticleSystem>() != null) return true;
            return false;
        }

        void Update()
        {
            if (!IsSpawned) return;
            if (Time.unscaledTime >= expiresAt) { Release(); return; }
            foreach (var particle in particles)
                if (particle != null && particle.IsAlive(true)) return;
            Release();
        }

        /// <summary>Release the current spawn immediately. Do not retain this reference after releasing.</summary>
        public void Release()
        {
            if (IsSpawned && owner != null) owner.Release(this);
        }

        /// <summary>For delayed callbacks, capture Version at spawn and release only that lease.</summary>
        public bool Release(uint expectedVersion)
        {
            if (!IsSpawned || Version != expectedVersion || owner == null) return false;
            owner.Release(this);
            return true;
        }

        public void Stop() => Release();

        internal void ReturnToPool(Transform poolParent)
        {
            IsSpawned = false;
            ResetParticles();
            gameObject.SetActive(false);
            transform.SetParent(poolParent, false);
            transform.localPosition = Vector3.zero;
            transform.localRotation = Quaternion.identity;
            transform.localScale = initialScale;
        }

        void ResetParticles()
        {
            if (particles == null) return;
            foreach (var particle in particles)
                if (particle != null) particle.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
        }

        internal void DestroyPooled()
        {
            IsSpawned = false;
            owner = null;
            ResetParticles();
            Destroy(gameObject);
        }

        void OnDisable()
        {
            // External deactivation must not leave an unavailable instance counted as active.
            if (IsSpawned) Release();
        }

        void OnDestroy()
        {
            if (owner != null) owner.ForgetDestroyed(this);
            owner = null;
            IsSpawned = false;
        }
    }
}
