using System.Collections.Generic;
using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    public struct MapCell
    {
        public bool ground, visited;
        public float height;
    }

    /// <summary>Remembers only local, visible physics samples. No whole-scene map or Brain output.</summary>
    [DefaultExecutionOrder(400)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunExplorationMap : MonoBehaviour
    {
        public const float CellSize = .5f;
        public BlindSugarRunSession stage;
        public BlindSugarRunLocalVisibility visibility;
        static readonly Dictionary<Vector2Int, MapCell> memory = new Dictionary<Vector2Int, MapCell>();
        static string memoryScene;
        readonly RaycastHit[] hits = new RaycastHit[32];
        readonly Collider[] overlaps = new Collider[16];
        FlyTerrainSensor sensor;
        float nextSample;
        public IReadOnlyDictionary<Vector2Int, MapCell> Cells => memory;
        public Vector3 PlayerPosition => stage?.fly == null ? Vector3.zero : stage.fly.Position;
        public Vector3 PlayerForward => stage?.fly == null ? Vector3.forward : stage.fly.transform.forward;
        public bool MappingActive { get; private set; }
        public int Revision { get; private set; }
        public int LastLocalQueries { get; private set; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetMemory() { memory.Clear(); memoryScene = null; }

        void Start()
        {
            if (stage == null) stage = FindAnyObjectByType<BlindSugarRunSession>();
            if (visibility == null) visibility = GetComponent<BlindSugarRunLocalVisibility>();
            // Keep exploration through same-stage retries; never carry it into a different level.
            if (memoryScene != gameObject.scene.path) { memory.Clear(); memoryScene = gameObject.scene.path; }
            var view = GetComponent<BlindSugarRunMinimapView>() ?? gameObject.AddComponent<BlindSugarRunMinimapView>();
            view.Configure(this, visibility == null ? null : visibility.stageCamera);
        }

        void Update()
        {
            if (Time.unscaledTime < nextSample) return;
            nextSample = Time.unscaledTime + .2f;
            MappingActive = false;
            if (stage?.fly == null || stage.State != BlindSugarRunSession.StageState.Playing) return;
            if (sensor == null) sensor = stage.fly.GetComponent<FlyTerrainSensor>();
            var observation = sensor?.Observation;
            if (sensor == null || !sensor.Fresh || observation == null || observation.queryOverflow ||
                !observation.groundPresent || observation.bodyUnsafe || Vector3.Dot(sensor.Up, Vector3.up) < .99f) return;
            MappingActive = true;
            ObserveLocal(PlayerPosition, observation.ground.point.y, visibility == null ? 3f : visibility.visibleRadius,
                Mathf.Max(.5f, sensor.MaximumDrop));
        }

        void ObserveLocal(Vector3 position, float groundHeight, float radius, float maximumDrop)
        {
            LastLocalQueries = 0;
            // Entire cells, including their corners, must lie inside the current local observation disk.
            float usableRadius = Mathf.Max(0f, radius - CellSize * .707107f);
            Vector2Int playerCell = CellAt(position);
            int reach = Mathf.CeilToInt(radius / CellSize);
            for (int z = playerCell.y - reach; z <= playerCell.y + reach; z++)
            for (int x = playerCell.x - reach; x <= playerCell.x + reach; x++)
            {
                var key = new Vector2Int(x, z);
                Vector3 center = new Vector3((x + .5f) * CellSize, groundHeight, (z + .5f) * CellSize);
                if (new Vector2(center.x - position.x, center.z - position.z).sqrMagnitude > usableRadius * usableRadius) continue;
                Vector3 origin = center + Vector3.up * .65f;
                if (Occupied(origin)) continue; // Inside a wall/overhead surface is unknown, not a cliff.
                bool found = Cast(origin, Vector3.down, .65f + maximumDrop, out var floor, out bool overflow);
                if (overflow) continue;
                Vector3 target = found ? floor.point + Vector3.up * .04f : center + Vector3.up * .04f;
                Vector3 ray = target - position;
                bool blocked = Cast(position, ray.normalized, Mathf.Max(0f, ray.magnitude - .06f), out _, out overflow);
                if (blocked || overflow) continue; // Do not discover terrain behind an occluding object.
                // Vertical faces and steep walls are not evidence of empty space beyond an edge.
                if (found && Vector3.Angle(floor.normal, Vector3.up) > 45f) continue;
                memory.TryGetValue(key, out var previous);
                var cell = new MapCell { ground = found, height = found ? floor.point.y : groundHeight - maximumDrop,
                    visited = previous.visited || (found && key == playerCell) };
                if (!memory.ContainsKey(key) || previous.ground != cell.ground || previous.visited != cell.visited ||
                    Mathf.Abs(previous.height - cell.height) > .01f)
                { memory[key] = cell; Revision++; }
            }
        }

        public static Vector2Int CellAt(Vector3 position) => new Vector2Int(Mathf.FloorToInt(position.x / CellSize), Mathf.FloorToInt(position.z / CellSize));

        bool External(Collider collider) => collider != null && !collider.isTrigger &&
            !collider.transform.IsChildOf(stage.fly.transform);

        bool Occupied(Vector3 origin)
        {
            int count = Physics.OverlapSphereNonAlloc(origin, .01f, overlaps, ~(1 << 31), QueryTriggerInteraction.Ignore);
            LastLocalQueries++;
            if (count == overlaps.Length) return true;
            for (int i = 0; i < count; i++) if (External(overlaps[i])) return true;
            return false;
        }

        bool Cast(Vector3 origin, Vector3 direction, float distance, out RaycastHit nearest, out bool overflow)
        {
            int count = Physics.RaycastNonAlloc(origin, direction, hits, distance, ~(1 << 31), QueryTriggerInteraction.Ignore);
            LastLocalQueries++;
            overflow = count == hits.Length; nearest = default;
            if (overflow) return false;
            float best = float.PositiveInfinity;
            for (int i = 0; i < count; i++)
                if (External(hits[i].collider) && hits[i].distance < best) { best = hits[i].distance; nearest = hits[i]; }
            return best < float.PositiveInfinity;
        }
    }
}
