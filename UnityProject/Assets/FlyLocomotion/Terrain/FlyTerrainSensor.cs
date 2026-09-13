using System;
using UnityEngine;

namespace FlyLocomotionPoC
{
    [Serializable] public sealed class FlySurfaceSample
    {
        public bool found, walkable, wideEnough;
        public Vector3 point, normal;
        public float distance, slope;
        public string surface = "";
    }
    [Serializable] public sealed class FlyNearbyObstacle
    {
        public string direction;
        public bool found;
        public float distance;
        public Vector3 point;
    }
    [Serializable] public sealed class FlyWorldObservation
    {
        public int sequence;
        public float sampledAt, bodyHeight, slope;
        public bool queryOverflow, groundPresent, forwardBlocked, bodyUnsafe;
        public string leftEdge = "unknown", rightEdge = "unknown", suggestedAction = "STOP";
        public FlySurfaceSample ground;
        public FlyNearbyObstacle[] surroundings;
    }

    // Local physics observations only. No map lookup, motor generation or body writes.
    [DisallowMultipleComponent]
    public sealed class FlyTerrainSensor : MonoBehaviour
    {
        [SerializeField] LayerMask terrainMask = ~0;
        [SerializeField, Range(.02f, .2f)] float sampleInterval = .05f;
        [SerializeField, Range(5f, 70f)] float maximumSlope = 40f;
        [SerializeField, Range(.05f, .4f)] float stepHeightFraction = .30f;
        [SerializeField, Range(.05f, .5f)] float maximumDropFraction = .20f;
        readonly RaycastHit[] hits = new RaycastHit[64];
        readonly Collider[] overlaps = new Collider[64];
        FlyBody body;
        float nextSample;
        int sequence;
        public FlyWorldObservation Observation { get; private set; }
        public Vector3 Up => Physics.gravity.sqrMagnitude > .001f ? -Physics.gravity.normalized : Vector3.up;
        public Vector3 Forward => Vector3.ProjectOnPlane(body.Thorax.transform.forward, Up).normalized;
        public Vector3 Right => Vector3.Cross(Up, Forward).normalized;
        public float Reach { get; private set; }
        public float MaximumStep => Reach * stepHeightFraction;
        public float MaximumDrop => Reach * maximumDropFraction;
        public bool Fresh => Observation != null && Time.unscaledTime - Observation.sampledAt <= .25f;
        public void Configure(FlyBody owner)
        {
            body = owner;
            Reach = .1f;
            foreach (var leg in body.Legs)
                if (leg != null) Reach = Mathf.Max(Reach, Vector3.Distance(leg.Femur.transform.position, leg.Tibia.transform.position)
                    + Vector3.Distance(leg.Tibia.transform.position, leg.FootProbePosition));
            SampleNow();
        }
        void Update() { if (body != null && Time.unscaledTime >= nextSample) SampleNow(); }
        bool External(Collider c) => c != null && !c.isTrigger && !c.transform.IsChildOf(body.transform);
        public bool Cast(Vector3 origin, Vector3 direction, float distance, float radius, out RaycastHit nearest)
        {
            nearest = default;
            int count = radius > 0f ? Physics.SphereCastNonAlloc(origin, radius, direction, hits, distance, terrainMask, QueryTriggerInteraction.Ignore)
                : Physics.RaycastNonAlloc(origin, direction, hits, distance, terrainMask, QueryTriggerInteraction.Ignore);
            if (count == hits.Length) { if (Observation != null) Observation.queryOverflow = true; return false; }
            float best = float.PositiveInfinity;
            for (int i = 0; i < count; i++)
                if (External(hits[i].collider) && hits[i].distance < best) { nearest = hits[i]; best = hits[i].distance; }
            return best < float.PositiveInfinity;
        }
        public FlySurfaceSample GroundAt(Vector3 position, float referenceHeight, float footRadius = 0f)
        {
            var sample = new FlySurfaceSample();
            float top = referenceHeight + MaximumStep + Reach * .25f;
            Vector3 origin = position + Up * (top - Vector3.Dot(position, Up));
            int occupied = Physics.OverlapSphereNonAlloc(origin, .001f * Reach, overlaps, terrainMask, QueryTriggerInteraction.Ignore);
            if (occupied == overlaps.Length) { if (Observation != null) Observation.queryOverflow = true; return sample; }
            for (int i = 0; i < occupied; i++) if (External(overlaps[i])) return sample;
            if (!Cast(origin, -Up, Reach * 2f, 0f, out var hit)) return sample;
            sample.found = true; sample.point = hit.point; sample.normal = hit.normal;
            sample.distance = hit.distance; sample.slope = Vector3.Angle(Up, hit.normal);
            sample.surface = hit.collider.name;
            sample.walkable = sample.slope <= maximumSlope;
            sample.wideEnough = sample.walkable;
            if (footRadius > 0f && sample.walkable)
            {
                // Require the centre AND all four rim samples; a thin edge is not a foot support.
                for (int i = 0; i < 4; i++)
                {
                    Vector3 offset = (i < 2 ? Right : Forward) * (i % 2 == 0 ? footRadius : -footRadius);
                    if (!Cast(origin + offset, -Up, Reach * 2f, 0f, out var rim)
                        || Vector3.Angle(Up, rim.normal) > maximumSlope
                        || Mathf.Abs(Vector3.Dot(rim.point - hit.point, Up)) > footRadius * 1.5f)
                        sample.wideEnough = false;
                }
            }
            return sample;
        }
        public float FootRadius(FlyLeg leg)
        {
            var c = leg.FootContact.GetComponent<SphereCollider>();
            return c == null ? Reach * .04f : Mathf.Max(c.bounds.extents.x, c.bounds.extents.y, c.bounds.extents.z);
        }
        string Edge(Vector3 side, float groundHeight)
        {
            float frontExtent = 0f;
            foreach (var leg in body.Legs)
                if (leg != null) frontExtent = Mathf.Max(frontExtent, Vector3.Dot(leg.FootProbePosition - body.Position, Forward));
            for (int i = 0; i < 2; i++)
            {
                Vector3 p = body.Position + side + Forward * (frontExtent + Reach * (i == 0 ? .12f : .4f));
                var s = GroundAt(p, groundHeight);
                if (!s.found || !s.walkable || groundHeight - Vector3.Dot(s.point, Up) > MaximumDrop)
                    return i == 0 ? "very_near" : "near";
            }
            return "safe";
        }
        void SampleNow()
        {
            nextSample = Time.unscaledTime + sampleInterval;
            var o = new FlyWorldObservation { sequence = ++sequence, sampledAt = Time.unscaledTime };
            Observation = o;
            o.ground = GroundAt(body.Position, Vector3.Dot(body.Position, Up));
            o.groundPresent = o.ground.found && o.ground.walkable;
            o.bodyHeight = o.ground.found ? Vector3.Dot(body.Position - o.ground.point, Up) : -1f;
            o.slope = o.ground.slope;
            o.bodyUnsafe = Vector3.Angle(body.Thorax.transform.up, Up) > 55f;
            o.surroundings = new FlyNearbyObstacle[8];
            float floor = o.groundPresent ? Vector3.Dot(o.ground.point, Up) : Vector3.Dot(body.Position, Up) - Reach;
            string[] names = { "front", "front-right", "right", "back-right", "back", "back-left", "left", "front-left" };
            float frontExtent = 0f, sideExtent = 0f;
            foreach (var leg in body.Legs)
                if (leg != null) { frontExtent = Mathf.Max(frontExtent, Vector3.Dot(leg.FootProbePosition - body.Position, Forward)); sideExtent = Mathf.Max(sideExtent, Mathf.Abs(Vector3.Dot(leg.FootProbePosition - body.Position, Right))); }
            for (int i = 0; i < 8; i++)
            {
                Vector3 direction = Quaternion.AngleAxis(i * 45f, Up) * Forward;
                var nearby = new FlyNearbyObstacle { direction = names[i], distance = Reach * 2f };
                o.surroundings[i] = nearby;
                for (int height = 0; height < 2; height++)
                {
                    Vector3 origin = body.Position + Up * (floor + (height == 0 ? Reach * .10f : o.bodyHeight) - Vector3.Dot(body.Position, Up));
                    if (Cast(origin, direction, Reach * 2f, Reach * .04f, out var obstacle) && obstacle.distance < nearby.distance)
                    { nearby.found = true; nearby.distance = obstacle.distance; nearby.point = obstacle.point; }
                    if (i == 0 && height == 1 && obstacle.collider != null && obstacle.distance <= frontExtent + Reach * .3f)
                        o.forwardBlocked = true;
                }
            }
            int n = Physics.OverlapSphereNonAlloc(body.Position, Reach * .12f, overlaps, terrainMask, QueryTriggerInteraction.Ignore);
            if (n == overlaps.Length) o.queryOverflow = true;
            for (int i = 0; i < n; i++) if (External(overlaps[i])) o.bodyUnsafe = true;
            var front = o.surroundings[0];
            if (front.found && front.distance <= frontExtent + Reach * .3f)
            {
                var top = GroundAt(front.point + Forward * Reach * .15f, floor, Reach * .04f);
                float rise = top.found ? Vector3.Dot(top.point, Up) - floor : float.PositiveInfinity;
                o.forwardBlocked |= !top.walkable || !top.wideEnough || rise > MaximumStep || rise < -MaximumDrop;
            }
            if (o.groundPresent)
            { o.leftEdge = Edge(-Right * sideExtent * .8f, floor); o.rightEdge = Edge(Right * sideExtent * .8f, floor); }
            o.suggestedAction = !o.forwardBlocked ? "FORWARD" :
                o.surroundings[2].distance > o.surroundings[6].distance ? "TURN_R" : "TURN_L";
            if (!o.groundPresent || o.queryOverflow || o.bodyUnsafe || o.leftEdge == "very_near" || o.rightEdge == "very_near") o.suggestedAction = "STOP";
        }
        void OnDrawGizmosSelected()
        {
            if (Observation == null || body == null) return;
            Gizmos.color = Color.cyan;
            foreach (var s in Observation.surroundings) if (s.found) Gizmos.DrawLine(body.Position, s.point);
            if (Observation.ground.found) Gizmos.DrawLine(body.Position, Observation.ground.point);
        }
    }
}
