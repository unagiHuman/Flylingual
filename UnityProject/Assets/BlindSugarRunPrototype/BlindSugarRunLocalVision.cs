using System;
using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    [Serializable] public sealed class VisualFacts { public string ground; public bool moving, stable, revisited; public VisualDirection[] directions; }
    [Serializable] public sealed class VisualDirection
    {
        public string direction, surface; public float distance; public string edge; public float edgeDistance;
        public string trend, alignment, slope;
    }

    /// <summary>Speech facts from this tick's visible .5m map cells only.</summary>
    [DefaultExecutionOrder(410)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunLocalVision : MonoBehaviour
    {
        const float Radius = 3f, SectorHalfAngle = 22.5f, VeryNearEdge = 1.5f;
        static readonly string[] DirectionNames = { "front", "front-right", "right", "back-right", "back", "back-left", "left", "front-left" };
        readonly float[] previousEdge = new float[8];
        readonly RaycastHit[] objectHits = new RaycastHit[32];
        BlindSugarRunExplorationMap map;
        FlyTerrainSensor sensor;
        long observedMapSequence = -1;
        bool fresh, haveForward, havePreviousPosition;
        float travelSinceVisit;
        Vector3 previousForward, previousPosition;
        Vector2Int previousCell;

        public VisualFacts Facts { get; private set; }
        public float SampledAt { get; private set; } = -1f;
        public bool Fresh => isActiveAndEnabled && fresh && map != null && map.MappingActive &&
            observedMapSequence == map.Sequence && Time.unscaledTime - SampledAt <= .25f;
        public long Sequence { get; private set; }
        public void Configure(BlindSugarRunExplorationMap owner) { map = owner; }
        void OnEnable() { Invalidate(); }
        void OnDisable() { Invalidate(); }

        void Update()
        {
            if (map == null) map = GetComponent<BlindSugarRunExplorationMap>();
            if (map == null || !map.MappingActive) { Invalidate(); return; }
            if (map.Sequence == observedMapSequence) return;
            if (map.stage?.fly == null || map.stage.State != BlindSugarRunSession.StageState.Playing || map.CurrentSamples.Count == 0)
            { Invalidate(); return; }
            if (sensor == null) sensor = map.stage.fly.GetComponent<FlyTerrainSensor>();
            var observation = sensor == null ? null : sensor.Observation;
            if (sensor == null || !sensor.Fresh || observation == null || observation.queryOverflow) { Invalidate(); return; }
            Sample(observation);
            observedMapSequence = map.Sequence; SampledAt = map.SampledAt; Sequence++; fresh = true;
        }

        void Sample(FlyWorldObservation observation)
        {
            Vector3 position = map.PlayerPosition, up = sensor.Up;
            Vector3 forward = sensor.Forward.sqrMagnitude > .0001f ? sensor.Forward : Vector3.forward;
            if (haveForward && Vector3.Angle(previousForward, forward) > 25f) ResetTrend();
            previousForward = forward; haveForward = true;
            string ground = observation.groundPresent ? Kind(observation.ground.surface) : "unknown";
            Vector2Int currentCell = BlindSugarRunExplorationMap.CellAt(position);
            if (map.CurrentSamples.TryGetValue(currentCell, out var beneath) && beneath.ground) ground = Kind(beneath.hitCollider);
            bool enteredCell = havePreviousPosition && currentCell != previousCell;
            if (havePreviousPosition)
            {
                travelSinceVisit += Vector3.ProjectOnPlane(position - previousPosition, up).magnitude;
            }
            previousPosition = position; previousCell = currentCell; havePreviousPosition = true;
            bool revisited = enteredCell && map.PlayerCellVisitedBeforeSample && travelSinceVisit >= 1f;
            if (revisited) travelSinceVisit = 0f;
            var facts = new VisualFacts {
                ground = ground,
                moving = map.stage.fly.LinearVelocity.magnitude > .03f || map.stage.fly.AngularVelocity.magnitude > .08f,
                stable = observation.groundPresent && !observation.bodyUnsafe && map.stage.fly.LinearVelocity.magnitude <= .03f && map.stage.fly.AngularVelocity.magnitude <= .08f,
                revisited = revisited, directions = new VisualDirection[8]
            };
            for (int i = 0; i < 8; i++)
                facts.directions[i] = Direction(i, DirectionNames[i], position, Quaternion.AngleAxis(i * 45f, up) * forward, forward, up, ground);
            Facts = facts;
        }

        VisualDirection Direction(int index, string name, Vector3 position, Vector3 sectorForward, Vector3 flyForward, Vector3 up, string footKind)
        {
            var result = new VisualDirection { direction = name, surface = "unknown", distance = -1f, edge = "unknown", edgeDistance = -1f,
                trend = "unknown", alignment = "unknown", slope = "unknown" };
            int coverage = 0;
            float nearestFloor = float.PositiveInfinity, nearestKnown = float.PositiveInfinity;
            BlindSugarRunCurrentSample floor = default, known = default;
            foreach (var pair in map.CurrentSamples)
            {
                Vector3 offset = Vector3.ProjectOnPlane(CellCenter(pair.Key) - position, up);
                float distance = offset.magnitude;
                if (distance > Radius || distance < .001f || Vector3.Angle(sectorForward, offset) > SectorHalfAngle) continue;
                coverage++;
                var sample = pair.Value;
                if (!sample.ground) continue;
                string kind = Kind(sample.hitCollider);
                if (distance < nearestFloor) { nearestFloor = distance; floor = sample; }
                if (kind != "unknown" && kind != footKind && distance < nearestKnown) { nearestKnown = distance; known = sample; }
            }
            if (nearestKnown < float.PositiveInfinity) Describe(ref result, known, nearestKnown, flyForward, up);
            else if (nearestFloor < float.PositiveInfinity) Describe(ref result, floor, nearestFloor, flyForward, up);
            // Eye-height obstacles are not floor samples. Only the first external ray hit is visible.
            int count = Physics.RaycastNonAlloc(position, sectorForward, objectHits,
                Mathf.Min(Radius, map.visibility == null ? Radius : map.visibility.visibleRadius), ~(1 << 31), QueryTriggerInteraction.Ignore);
            if (count < objectHits.Length)
            {
                float closest = float.PositiveInfinity; RaycastHit visible = default;
                for (int h = 0; h < count; h++)
                    if (objectHits[h].collider != null && !objectHits[h].collider.transform.IsChildOf(map.stage.fly.transform)
                        && objectHits[h].distance < closest) { closest = objectHits[h].distance; visible = objectHits[h]; }
                if (closest < float.PositiveInfinity && (nearestKnown == float.PositiveInfinity || closest < nearestKnown))
                {
                    result.surface = Kind(visible.collider);
                    if (result.surface == "unknown") result.surface = "obstacle";
                    result.distance = closest; result.slope = "unknown";
                    result.alignment = Alignment(visible.collider, flyForward, up);
                }
            }
            FindEdge(position, sectorForward, up, ref result);
            if (result.edgeDistance < 0f && coverage >= 3 && nearestFloor < float.PositiveInfinity) result.edge = "clear";
            UpdateTrend(index, ref result);
            return result;
        }

        void FindEdge(Vector3 position, Vector3 sectorForward, Vector3 up, ref VisualDirection result)
        {
            float nearest = float.PositiveInfinity;
            foreach (var pair in map.CurrentSamples)
            {
                if (!pair.Value.ground) continue;
                Vector2Int key = pair.Key;
                for (int side = 0; side < 4; side++)
                {
                    Vector2Int neighbor = side == 0 ? key + Vector2Int.right : side == 1 ? key + Vector2Int.left : side == 2 ? key + Vector2Int.up : key + Vector2Int.down;
                    if (!map.CurrentSamples.TryGetValue(neighbor, out var other) || other.ground) continue;
                    Vector3 offset = Vector3.ProjectOnPlane((CellCenter(key) + CellCenter(neighbor)) * .5f - position, up);
                    float distance = offset.magnitude;
                    if (distance > .001f && distance <= Radius && Vector3.Angle(sectorForward, offset) <= SectorHalfAngle) nearest = Mathf.Min(nearest, distance);
                }
            }
            if (nearest == float.PositiveInfinity) return;
            result.edgeDistance = nearest; result.edge = nearest <= VeryNearEdge ? "very_near" : "near";
        }

        void Describe(ref VisualDirection result, BlindSugarRunCurrentSample sample, float distance, Vector3 flyForward, Vector3 up)
        {
            result.surface = Kind(sample.hitCollider); result.distance = Mathf.Clamp(distance, 0f, Radius);
            float slope = Vector3.Angle(sample.normal, up);
            float rise = -Vector3.Dot(sample.normal, flyForward);
            result.slope = slope <= 12f ? "level" : slope <= 45f && Mathf.Abs(rise) > .03f ? (rise > 0 ? "up" : "down") : "unknown";
            result.alignment = Alignment(sample.hitCollider, flyForward, up);
        }

        static Vector3 CellCenter(Vector2Int key) => new Vector3((key.x + .5f) * BlindSugarRunExplorationMap.CellSize, 0f, (key.y + .5f) * BlindSugarRunExplorationMap.CellSize);
        static string Kind(string name)
        {
            switch (name) { case "StartArea": case "PlanningArea": return "desk"; case "NarrowRoute": case "WideRouteA": case "WideRouteB": case "WideRouteC": case "WideConnectionPad1": case "WideConnectionPad2": case "GoalArea": return "path"; case "RulerBridge": return "ruler"; case "BookPlatform": case "BookPages": case "BookTopCover": return "book"; case "Plate": return "plate"; case "Sugar0": case "Sugar1": case "Sugar2": return "sugar"; default: return "unknown"; }
        }
        static string Kind(Collider collider)
        {
            if (collider == null) return "unknown";
            var marker = collider.GetComponent<BlindSugarRunVisibleObject>();
            return marker != null && ValidKind(marker.kind) ? marker.kind : Kind(collider.name);
        }
        static bool ValidKind(string value) => value == "unknown" || value == "desk" || value == "ruler" || value == "book" || value == "plate" || value == "sugar" || value == "path" || value == "obstacle";
        static string Alignment(Collider collider, Vector3 flyForward, Vector3 up)
        {
            if (collider == null) return "unknown";
            var marker = collider.GetComponent<BlindSugarRunVisibleObject>();
            Vector3 heading;
            if (marker != null && marker.hasVisibleHeading) heading = marker.transform.TransformDirection(marker.localHeading);
            else if (collider.name == "RulerBridge") heading = collider.transform.forward;
            else return "unknown";
            heading = Vector3.ProjectOnPlane(heading, up);
            if (heading.sqrMagnitude < .0001f) return "unknown";
            if (Vector3.Dot(heading, flyForward) < 0f) heading = -heading;
            float angle = Vector3.SignedAngle(flyForward, heading.normalized, up);
            if (Mathf.Abs(angle) <= 8f) return "center";
            return Mathf.Abs(angle) <= 45f ? (angle > 0f ? "right" : "left") : "unknown";
        }
        void UpdateTrend(int index, ref VisualDirection result)
        {
            if (result.edgeDistance < 0f) { previousEdge[index] = -1f; return; }
            if (previousEdge[index] >= 0f)
            {
                float delta = result.edgeDistance - previousEdge[index];
                result.trend = Mathf.Abs(delta) < .12f ? "steady" : delta < 0f ? "closer" : "farther";
                if (Mathf.Abs(delta) < .12f) return; // Accumulate slow approaches instead of losing them every tick.
            }
            previousEdge[index] = result.edgeDistance;
        }
        void ResetTrend() { for (int i = 0; i < previousEdge.Length; i++) previousEdge[i] = -1f; haveForward = false; }
        void Invalidate() { fresh = false; SampledAt = -1f; observedMapSequence = -1; havePreviousPosition = false; travelSinceVisit = 0f; ResetTrend(); }
    }
}
