using System.Collections.Generic;
using Flylingual.Conversation;
using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Game-authored route observation only. Actions still travel through Bridge and Brain.</summary>
    [DefaultExecutionOrder(500)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunRouteHint : MonoBehaviour
    {
        // Follow the wide detour around the gap. Never aim straight from the book to the goal.
        static readonly string[] Supports = { "StartArea", "PlanningArea", "RulerBridge", "BookPlatform",
            "WideRouteA", "WideConnectionPad1", "WideRouteB", "WideConnectionPad2", "WideRouteC", "GoalArea" };
        readonly List<Collider> supports = new List<Collider>();
        readonly List<Vector3> route = new List<Vector3>();
        BlindSugarRunSession stage;
        ConversationSessionController conversation;
        FlyTerrainSensor sensor;
        float nextSample, sampledAt = -1;
        long sequence;
        Vector3 waypoint;
        bool waypointValid;
        bool canTurnSafely, forwardPathSupported;
        string recommendedAction;
        bool Fresh => waypointValid && Time.unscaledTime - sampledAt <= .25f && Time.timeScale > 0
            && stage != null && stage.State == BlindSugarRunSession.StageState.Playing
            && conversation != null && conversation.HasFreshBrain && conversation.BodyControlActive
            && sensor != null && sensor.Fresh && sensor.Observation != null
            && !sensor.Observation.queryOverflow && sensor.Observation.groundPresent && !sensor.Observation.bodyUnsafe;
        public string RecommendedAction => Fresh ? recommendedAction : null;
        // Turning is checked around the body, separately from edges ahead of the body.
        public bool CanTurnSafely => Fresh && canTurnSafely;
        // This describes translation along the CURRENT heading, not toward an unaligned waypoint.
        public bool ForwardPathSupported => Fresh && forwardPathSupported;

        void Start()
        {
            stage = GetComponent<BlindSugarRunSession>();
            var volumes = stage != null && stage.killVolume != null ? stage.killVolume.transform.parent : null;
            var geometry = volumes != null && volumes.name == "Volumes" && volumes.parent != null
                ? volumes.parent.Find("EnvironmentGeometry") : null;
            if (geometry == null || geometry.gameObject.scene != gameObject.scene) return;
            foreach (string name in Supports)
            {
                Transform match = null;
                foreach (Transform child in geometry)
                    if (child.name == name) { if (match != null) { supports.Clear(); return; } match = child; }
                var candidates = match == null ? null : match.GetComponents<Collider>();
                if (candidates == null || candidates.Length != 1 || candidates[0].isTrigger)
                { supports.Clear(); return; }
                supports.Add(candidates[0]);
            }
        }

        public bool TryGetWaypoint(out Vector3 point)
        {
            point = waypoint;
            return Fresh;
        }

        void Update()
        {
            if (Time.unscaledTime < nextSample) return;
            nextSample = Time.unscaledTime + .1f;
            waypointValid = false;
            canTurnSafely = forwardPathSupported = false;
            recommendedAction = null;
            if (stage == null || stage.fly == null || stage.fly.Thorax == null
                || stage.State != BlindSugarRunSession.StageState.Playing || Time.timeScale <= 0) return;
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            if (sensor == null) sensor = stage.fly.GetComponent<FlyTerrainSensor>();
            var body = conversation == null ? null : conversation.GetComponent<NativeConversationBody>();
            var o = sensor == null ? null : sensor.Observation;
            if (conversation == null || !conversation.HasFreshBrain || !conversation.BodyControlActive
                || body == null || !body.BodyActive || !string.IsNullOrEmpty(body.Fault)) return;
            string action = null;
            if (sensor != null && sensor.Fresh && o != null && !o.queryOverflow && o.groundPresent
                && o.ground != null && !o.bodyUnsafe && stage.fly.GroundContactCount > 0
                && Vector3.Dot(sensor.Up, Vector3.up) > .99f && BuildRoute())
            {
                sampledAt = Time.unscaledTime;
                float floor = o.ground.point.y;
                if (FindWaypoint(stage.fly.Position, floor, out waypoint))
                {
                    waypointValid = true;
                    Vector3 delta = Vector3.ProjectOnPlane(waypoint - stage.fly.Position, Vector3.up);
                    float angle = Vector3.SignedAngle(sensor.Forward, delta, Vector3.up);
                    canTurnSafely = SupportedTurn(angle, floor);
                    forwardPathSupported = !o.forwardBlocked
                        && SupportedSegment(stage.fly.Position, stage.fly.Position + sensor.Forward * 2f, floor);
                    if (delta.magnitude < .35f) action = "STOP";
                    else if (Mathf.Abs(angle) > 18f)
                        action = canTurnSafely ? (angle > 0 ? "TURN_R" : "TURN_L") : null;
                    else if (forwardPathSupported)
                        action = "FORWARD";
                }
            }
            // Null explicitly invalidates a previous usable hint. Queue age is added by the transport.
            float ageMs = action == null || o == null ? 0f : Mathf.Max(0f, (Time.unscaledTime - o.sampledAt) * 1000f);
            recommendedAction = action;
            conversation.TrySendGoalRouteHint(++sequence, action, ageMs);
        }

        bool BuildRoute()
        {
            route.Clear();
            if (supports.Count != Supports.Length) return false;
            foreach (Collider support in supports)
            {
                if (support == null || !support.enabled || !support.gameObject.activeInHierarchy) return false;
                // WideRouteA meets the book at its negative-forward endpoint; its centre alone cuts the corner.
                if (support.name == "WideRouteA")
                {
                    var box = support as BoxCollider;
                    if (box == null) return false;
                    route.Add(box.transform.TransformPoint(box.center - Vector3.forward * box.size.z * .5f));
                }
                route.Add(support.bounds.center);
            }
            return true;
        }

        bool FindWaypoint(Vector3 position, float floor, out Vector3 target)
        {
            target = default;
            float best = float.PositiveInfinity;
            int bestSegment = -1;
            float bestT = 0f;
            for (int i = 0; i < route.Count - 1; i++)
            {
                Vector3 start = route[i], end = route[i + 1];
                start.y = end.y = position.y;
                Vector3 segment = end - start;
                float length = segment.magnitude;
                if (length < .01f) continue;
                float t = Mathf.Clamp01(Vector3.Dot(position - start, segment) / segment.sqrMagnitude);
                Vector3 closest = start + segment * t;
                float distance = (position - closest).sqrMagnitude;
                if (distance > best + .0001f) continue;
                best = distance;
                bestSegment = i; bestT = t;
                target = closest;
            }
            if (bestSegment < 0 || best > 36f) return false;
            Vector3 projection = target;
            Vector3 junction = route[bestSegment + 1];
            junction.y = position.y;
            // Join the next authored junction when off-centre instead of walking backwards to an old
            // centreline projection. The entire body-width corridor must still be supported.
            if (best > 1f && Vector3.Distance(position, junction) <= 6f
                && Vector3.Distance(position, junction) > .35f && SupportedSegment(position, junction, floor))
            { target = junction; return true; }
            // Carry a short lookahead across a nearby joint only if its actual connecting corridor is safe.
            // If that chord cuts a corner, stop the lookahead at the junction and approach it first.
            if (best <= 1f || Vector3.Distance(position, junction) <= 2f)
            {
                float remaining = 2f;
                for (int i = bestSegment; i < route.Count - 1; i++)
                {
                    Vector3 start = route[i], end = route[i + 1];
                    start.y = end.y = position.y;
                    if (i == bestSegment) start = Vector3.Lerp(start, end, bestT);
                    float length = Vector3.Distance(start, end);
                    target = Vector3.MoveTowards(start, end, remaining);
                    if (length >= remaining) break;
                    remaining -= length;
                }
                if (SupportedSegment(position, target, floor)) return true;
                if (Vector3.Distance(position, junction) > .35f && SupportedSegment(position, junction, floor))
                { target = junction; return true; }
            }
            target = projection;
            return SupportedSegment(position, target, floor);
        }

        bool SupportedTurn(float angle, float floor)
        {
            // Sweep the observed foot positions through the required yaw, including each foot's rim.
            // A cliff detected only in front does not prohibit a supported rotation in place.
            // Maximum arc spacing is 0.2m, with an additional 7.5-degree angular bound.
            float radius = 0f;
            int feet = 0;
            foreach (var leg in stage.fly.Legs)
                if (leg != null)
                {
                    radius = Mathf.Max(radius, Vector3.ProjectOnPlane(
                        leg.FootProbePosition - stage.fly.Position, Vector3.up).magnitude + sensor.FootRadius(leg));
                    feet++;
                }
            if (feet == 0 || !SupportedPoint(stage.fly.Position, floor)) return false;
            int steps = Mathf.Max(1, Mathf.CeilToInt(Mathf.Max(Mathf.Abs(angle) / 7.5f,
                Mathf.Abs(angle) * Mathf.Deg2Rad * radius / .2f)));
            for (int i = 0; i <= steps; i++)
            {
                Quaternion yaw = Quaternion.AngleAxis(angle * i / steps, Vector3.up);
                int supported = 0;
                bool left = false, right = false, front = false, back = false;
                foreach (var leg in stage.fly.Legs)
                {
                    if (leg == null) continue;
                    Vector3 foot = stage.fly.Position + yaw * Vector3.ProjectOnPlane(
                        leg.FootProbePosition - stage.fly.Position, Vector3.up);
                    float pad = sensor.FootRadius(leg) + .05f;
                    bool grounded = SupportedPoint(foot, floor);
                    for (int rim = 0; rim < 4; rim++)
                    {
                        Vector3 offset = (rim < 2 ? Vector3.right : Vector3.forward) * (rim % 2 == 0 ? pad : -pad);
                        grounded &= SupportedPoint(foot + offset, floor);
                    }
                    if (!grounded) continue;
                    supported++;
                    Vector3 relative = Quaternion.Inverse(yaw) * (foot - stage.fly.Position);
                    float lateral = Vector3.Dot(relative, sensor.Right), longitudinal = Vector3.Dot(relative, sensor.Forward);
                    left |= lateral < 0; right |= lateral > 0;
                    front |= longitudinal > 0; back |= longitudinal < 0;
                }
                // Some legs can overhang a corner. Retain four supported feet,
                // spanning both sides and front/back, throughout the sweep.
                if (supported < 4 || !left || !right || !front || !back) return false;
            }
            return true;
        }

        bool SupportedPoint(Vector3 position, float floor)
        {
            var sample = sensor.GroundAt(position, floor);
            return !sensor.Observation.queryOverflow && sample.found && sample.walkable
                && sample.point.y >= floor - sensor.MaximumDrop && sample.point.y <= floor + sensor.MaximumStep;
        }

        bool SupportedSegment(Vector3 from, Vector3 to, float floor)
        {
            Vector3 delta = Vector3.ProjectOnPlane(to - from, Vector3.up);
            if (delta.magnitude > 6f) return false;
            Vector3 side = delta.sqrMagnitude > .001f ? Vector3.Cross(Vector3.up, delta.normalized) : sensor.Right;
            float margin = Mathf.Max(.5f, sensor.Reach * .55f);
            foreach (var leg in stage.fly.Legs)
                if (leg != null) margin = Mathf.Max(margin,
                    Mathf.Abs(Vector3.Dot(leg.FootProbePosition - stage.fly.Position, side)) + sensor.FootRadius(leg));
            int steps = Mathf.Max(1, Mathf.CeilToInt(delta.magnitude / .4f));
            int widthSteps = Mathf.Max(2, Mathf.CeilToInt(margin * 2f / .4f));
            for (int i = 0; i <= steps; i++)
            for (int rim = 0; rim <= widthSteps; rim++)
            {
                float across = Mathf.Lerp(-margin, margin, (float)rim / widthSteps);
                if (!SupportedPoint(from + delta * ((float)i / steps) + side * across, floor))
                    return false;
            }
            return true;
        }
    }
}
