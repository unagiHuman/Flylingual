using System;
using System.Collections.Generic;
using Flylingual.Conversation;
using FlyLocomotionPoC;
using UnityEngine;
using UnityEngine.Rendering;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Bounded game events; these events are not measured neural reward responses.</summary>
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunEnvironmentFeedback : MonoBehaviour
    {
        sealed class Pending { public string kind, source; public long sequence; public double at; }
        readonly string runId = Guid.NewGuid().ToString("N");
        readonly Queue<Pending> pending = new Queue<Pending>();
        readonly List<SugarTraceZone> zones = new List<SugarTraceZone>();
        readonly List<Material> materials = new List<Material>();
        BlindSugarRunSession stage;
        ConversationSessionController conversation;
        FlyTerrainSensor sensor;
        int epoch = -1, generation = -1;
        long sequence;
        bool registered, threat, terminal;
        double nextRegistration;

        void Start()
        {
            stage = GetComponent<BlindSugarRunSession>();
            var volumes = stage != null && stage.killVolume != null ? stage.killVolume.transform.parent : null;
            var environment = volumes != null && volumes.name == "Volumes" ? volumes.parent : null;
            var geometry = environment != null ? environment.Find("EnvironmentGeometry") : null;
            if (geometry == null || geometry.gameObject.scene != gameObject.scene) return;
            CreateZone(geometry, "PlanningArea", "planning_juice");
            CreateZone(geometry, "WideConnectionPad1", "connection_juice");
        }

        void CreateZone(Transform geometry, string supportName, string id)
        {
            Transform support = null;
            foreach (Transform child in geometry)
                if (child.name == supportName) { if (support != null) return; support = child; }
            if (support == null) return;
            var colliders = support.GetComponents<BoxCollider>();
            var filter = support.GetComponent<MeshFilter>();
            var renderer = support.GetComponent<MeshRenderer>();
            if (colliders.Length != 1 || colliders[0].isTrigger || !colliders[0].enabled
                || filter == null || filter.sharedMesh == null || renderer == null || renderer.sharedMaterial == null
                || Vector3.Dot(support.up, Vector3.up) < .999f || colliders[0].bounds.size.x < 8
                || colliders[0].bounds.size.z < 8) return;
            var obj = new GameObject("SugarTraceZone " + id);
            obj.transform.SetParent(transform, false);
            var zone = obj.AddComponent<SugarTraceZone>(); zone.Configure(colliders[0], this, id); zones.Add(zone);
            // Reuse authored geometry, flattened into a small juice stain. No physics component.
            var mesh = filter.sharedMesh;
            Vector3 extent = mesh.bounds.size;
            if (extent.x <= 0 || extent.y <= 0 || extent.z <= 0) return;
            var stain = new GameObject("Juice stain"); stain.transform.SetParent(obj.transform, false);
            float width = support.TransformVector(Vector3.right * colliders[0].size.x).magnitude * .7f;
            Vector3 scale = new Vector3(width / extent.x, .012f / extent.y, SugarTraceZone.TraceDepth / extent.z);
            stain.transform.localScale = scale;
            stain.transform.rotation = support.rotation;
            stain.transform.position = new Vector3(colliders[0].bounds.center.x, colliders[0].bounds.max.y + .012f,
                colliders[0].bounds.center.z) - support.rotation * Vector3.Scale(mesh.bounds.center, scale);
            stain.AddComponent<MeshFilter>().sharedMesh = mesh;
            var paint = new Material(renderer.sharedMaterial) { name = "Juice stain (runtime)" };
            paint.color = new Color(.8f, .32f, .055f); materials.Add(paint);
            var visual = stain.AddComponent<MeshRenderer>(); visual.sharedMaterial = paint;
            visual.shadowCastingMode = ShadowCastingMode.Off; visual.receiveShadows = false;
        }

        bool BindScope()
        {
            if (stage == null) stage = GetComponent<BlindSugarRunSession>();
            if (conversation == null) conversation = FindFirstObjectByType<ConversationSessionController>();
            if (conversation == null || stage == null) return false;
            if (epoch != conversation.ControlEpoch || generation != conversation.ConversationGeneration)
            {
                pending.Clear(); registered = false; nextRegistration = 0; threat = false;
                epoch = conversation.ControlEpoch; generation = conversation.ConversationGeneration;
            }
            return generation >= 0;
        }

        void Update()
        {
            if (!BindScope()) return;
            Flush();
            if (terminal || stage.State != BlindSugarRunSession.StageState.Playing || Time.timeScale <= 0
                || !conversation.HasFreshBrain || !conversation.BodyControlActive || stage.fly == null) return;
            if (sensor == null) sensor = stage.fly.GetComponent<FlyTerrainSensor>();
            foreach (var zone in zones) zone.Sample(stage.fly, sensor);
        }

        public void Record(string kind, string sourceId)
        {
            if (terminal || !BindScope()) return;
            Flush();
            if (pending.Count >= 8) return;
            pending.Enqueue(new Pending { kind = kind, source = sourceId,
                at = Time.realtimeSinceStartupAsDouble });
            Flush();
        }

        void Flush()
        {
            if (conversation == null) return;
            double now = Time.realtimeSinceStartupAsDouble;
            if (!registered)
            {
                if (terminal || now < nextRegistration) return;
                nextRegistration = now + .25;
                registered = conversation.TrySendEnvironmentEvent(runId, stage.Attempt, ++sequence, "run_started", "stage", 0);
                if (!registered) return;
            }
            while (pending.Count > 0)
            {
                var item = pending.Peek(); float age = (float)((now - item.at) * 1000);
                if (age < 0 || age > 750) { pending.Dequeue(); continue; }
                if (item.sequence == 0) item.sequence = ++sequence;
                if (!conversation.TrySendEnvironmentEvent(runId, stage.Attempt, item.sequence, item.kind, item.source, age)) return;
                pending.Dequeue();
            }
        }

        public void ThreatStarted() { BindScope(); if (threat || terminal) return; threat = true; Record("threat_started", "idle_swatter"); }
        public void ThreatEnded(bool escaped)
        {
            BindScope();
            if (!threat) return;
            threat = false; Record(escaped ? "threat_ended" : "threat_cancelled", "idle_swatter");
        }
        public void Finish(bool healthyFall, bool swatted = false)
        {
            if (terminal) return;
            ThreatEnded(false);
            if (healthyFall || swatted) Record(swatted ? "swatted" : "fall", swatted ? "idle_swatter" : "fall");
            terminal = true;
        }
        void OnDisable() { ThreatEnded(false); pending.Clear(); }
        void OnDestroy() { foreach (var material in materials) if (material != null) Destroy(material); }
    }
}
