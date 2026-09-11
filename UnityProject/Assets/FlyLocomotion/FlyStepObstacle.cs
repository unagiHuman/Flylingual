using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyStepObstacle : MonoBehaviour
    {
        public struct LegContactSnapshot
        {
            public bool top;
            public bool front;
            public Vector3 point;
            public Vector3 normal;
            public Vector3 relativeVelocity;
            public float tangentialSpeed;
            public float impulseMagnitude;
            public float normalImpulseMagnitude;
            public float relativeNormalVelocity;
            public float fixedTime;
        }

        [SerializeField] private float obstacleHeight = 0.02f;
        [SerializeField] private float frontX = 1.8f;
        [SerializeField] private float depth = 0.8f;
        [SerializeField] private float width = 8f;
        [SerializeField] private Transform upperPlatform;
        [SerializeField] private float upperPlatformLength = 8f;

        private int frontContactEvents;
        private int topContactEvents;
        private float frontContactSeconds;
        private float topContactSeconds;
        private readonly Dictionary<string, int> frontLegEvents = new Dictionary<string, int>();
        private readonly Dictionary<string, int> topLegEvents = new Dictionary<string, int>();
        private readonly Dictionary<string, float> frontLegSeconds = new Dictionary<string, float>();
        private readonly Dictionary<string, float> topLegSeconds = new Dictionary<string, float>();
        private readonly Dictionary<string, LegContactSnapshot> legContactSnapshots = new Dictionary<string, LegContactSnapshot>();

        public float ObstacleHeight => obstacleHeight;
        public float FrontX => frontX;
        public float UpperPlatformStartX => frontX + depth;
        public float UpperPlatformEndX => UpperPlatformStartX + upperPlatformLength;
        public float TopSurfaceStartX => frontX;
        public float TopSurfaceEndX => UpperPlatformEndX;
        public float UpperPlatformHalfWidth => width * 0.5f;
        public int FrontContactEvents => frontContactEvents;
        public int TopContactEvents => topContactEvents;
        public float FrontContactSeconds => frontContactSeconds;
        public float TopContactSeconds => topContactSeconds;

        public string ClassifyContactPoint(Vector3 point)
        {
            if (point.y >= obstacleHeight - 0.015f)
            {
                return "TOP";
            }

            if (point.x <= frontX + 0.06f)
            {
                return "FRONT";
            }

            return "STEP";
        }

        public void Configure(float height, float frontPositionX, float obstacleDepth, float obstacleWidth, Transform upper, float upperLength)
        {
            obstacleHeight = Mathf.Max(0.001f, height);
            frontX = frontPositionX;
            depth = Mathf.Max(0.05f, obstacleDepth);
            width = Mathf.Max(1f, obstacleWidth);
            upperPlatform = upper;
            upperPlatformLength = Mathf.Max(1f, upperLength);
            ApplyGeometry();
        }

        private void Awake()
        {
            string heightArgument = GetCommandLineValue("-flyStepHeight");
            if (float.TryParse(heightArgument, NumberStyles.Float, CultureInfo.InvariantCulture, out float overrideHeight))
            {
                obstacleHeight = Mathf.Max(0.001f, overrideHeight);
            }

            ApplyGeometry();
        }

        private void ApplyGeometry()
        {
            transform.position = new Vector3(frontX + depth * 0.5f, obstacleHeight * 0.5f, 0f);
            transform.localScale = new Vector3(depth, obstacleHeight, width);
            if (upperPlatform != null)
            {
                upperPlatform.position = new Vector3(UpperPlatformStartX + upperPlatformLength * 0.5f, obstacleHeight - 0.05f, 0f);
                upperPlatform.localScale = new Vector3(upperPlatformLength, 0.1f, width);
            }
        }

        private void OnCollisionStay(Collision collision)
        {
            FlyLeg leg = collision.collider == null ? null : collision.collider.GetComponentInParent<FlyLeg>();
            if (leg == null)
            {
                return;
            }


            bool front = false;
            bool top = false;
            Vector3 pointSum = Vector3.zero;
            Vector3 normalSum = Vector3.zero;
            int relevantContacts = 0;
            ContactPoint[] contacts = collision.contacts;
            for (int i = 0; i < contacts.Length; i++)
            {
                Vector3 point = contacts[i].point;
                if (point.y >= obstacleHeight - 0.015f)
                {
                    top = true;
                    pointSum += point;
                    normalSum += contacts[i].normal;
                    relevantContacts++;
                }
                else if (point.x <= frontX + 0.06f)
                {
                    front = true;
                    pointSum += point;
                    normalSum += contacts[i].normal;
                    relevantContacts++;
                }
            }

            if (front || top)
            {
                Vector3 normal = relevantContacts > 0 ? normalSum.normalized : Vector3.zero;
                Vector3 relativeVelocity = collision.relativeVelocity;
                Vector3 tangentialVelocity = relativeVelocity - Vector3.Project(relativeVelocity, normal);
                legContactSnapshots[leg.LegId] = new LegContactSnapshot
                {
                    top = top,
                    front = front,
                    point = relevantContacts > 0 ? pointSum / relevantContacts : Vector3.zero,
                    normal = normal,
                    relativeVelocity = relativeVelocity,
                    tangentialSpeed = tangentialVelocity.magnitude,
                    impulseMagnitude = collision.impulse.magnitude,
                    normalImpulseMagnitude = Mathf.Abs(Vector3.Dot(collision.impulse, normal)),
                    relativeNormalVelocity = Vector3.Dot(relativeVelocity, normal),
                    fixedTime = Time.fixedTime
                };
            }

            if (front)
            {
                frontContactEvents++;
                frontContactSeconds += Time.fixedDeltaTime;
                RecordLeg(frontLegEvents, frontLegSeconds, leg.LegId);
            }

            if (top)
            {
                topContactEvents++;
                topContactSeconds += Time.fixedDeltaTime;
                RecordLeg(topLegEvents, topLegSeconds, leg.LegId);
            }
        }

        public int GetFrontLegEvents(string group)
        {
            return GetGroupValue(frontLegEvents, group);
        }

        public int GetTopLegEvents(string group)
        {
            return GetGroupValue(topLegEvents, group);
        }

        public float GetFrontLegSeconds(string group)
        {
            return GetGroupValue(frontLegSeconds, group);
        }

        public float GetTopLegSeconds(string group)
        {
            return GetGroupValue(topLegSeconds, group);
        }

        public int GetFrontLegEventsForLeg(string legId)
        {
            return GetLegValue(frontLegEvents, legId);
        }

        public int GetTopLegEventsForLeg(string legId)
        {
            return GetLegValue(topLegEvents, legId);
        }

        public float GetFrontLegSecondsForLeg(string legId)
        {
            return GetLegValue(frontLegSeconds, legId);
        }

        public float GetTopLegSecondsForLeg(string legId)
        {
            return GetLegValue(topLegSeconds, legId);
        }

        public bool TryGetLegContactSnapshot(string legId, out LegContactSnapshot snapshot)
        {
            if (!string.IsNullOrEmpty(legId) && legContactSnapshots.TryGetValue(legId, out snapshot) &&
                Mathf.Abs(Time.fixedTime - snapshot.fixedTime) <= Time.fixedDeltaTime * 1.5f)
            {
                return true;
            }

            snapshot = default;
            return false;
        }

        private static void RecordLeg(Dictionary<string, int> eventsByLeg, Dictionary<string, float> secondsByLeg, string legId)
        {
            if (string.IsNullOrEmpty(legId))
            {
                return;
            }

            eventsByLeg[legId] = eventsByLeg.TryGetValue(legId, out int count) ? count + 1 : 1;
            secondsByLeg[legId] = secondsByLeg.TryGetValue(legId, out float seconds)
                ? seconds + Time.fixedDeltaTime
                : Time.fixedDeltaTime;
        }

        private static int GetGroupValue(Dictionary<string, int> values, string group)
        {
            int total = 0;
            foreach (KeyValuePair<string, int> pair in values)
            {
                if (pair.Key.EndsWith(group, StringComparison.Ordinal))
                {
                    total += pair.Value;
                }
            }

            return total;
        }

        private static float GetGroupValue(Dictionary<string, float> values, string group)
        {
            float total = 0f;
            foreach (KeyValuePair<string, float> pair in values)
            {
                if (pair.Key.EndsWith(group, StringComparison.Ordinal))
                {
                    total += pair.Value;
                }
            }

            return total;
        }

        private static int GetLegValue(Dictionary<string, int> values, string legId)
        {
            return !string.IsNullOrEmpty(legId) && values.TryGetValue(legId, out int value) ? value : 0;
        }

        private static float GetLegValue(Dictionary<string, float> values, string legId)
        {
            return !string.IsNullOrEmpty(legId) && values.TryGetValue(legId, out float value) ? value : 0f;
        }

        private static string GetCommandLineValue(string name)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name)
                {
                    return arguments[i + 1];
                }
            }

            return string.Empty;
        }
    }
}
