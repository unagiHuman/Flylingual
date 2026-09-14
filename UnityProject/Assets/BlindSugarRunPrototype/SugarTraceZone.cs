using FlyLocomotionPoC;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Contact observation only; no collider, reward input or body changes.</summary>
    public sealed class SugarTraceZone : MonoBehaviour
    {
        public const float TraceDepth = 1.7f;
        BoxCollider surface;
        BlindSugarRunEnvironmentFeedback feedback;
        string sourceId;
        readonly SugarTraceContactState contact = new SugarTraceContactState();
        public void Configure(BoxCollider support, BlindSugarRunEnvironmentFeedback owner, string id)
        { surface = support; feedback = owner; sourceId = id; }

        public void Sample(FlyBody fly, FlyTerrainSensor sensor)
        {
            if (contact.Consumed || surface == null || !surface.enabled || !surface.gameObject.activeInHierarchy
                || fly == null || sensor == null) return;
            var observation = sensor.Observation;
            bool valid = fly.GroundContactCount > 0 && sensor.Fresh && observation != null && !observation.queryOverflow && !observation.bodyUnsafe
                && observation.groundPresent && observation.ground != null && observation.ground.surface == surface.name;
            if (!valid) return;
            Vector3 p = surface.transform.InverseTransformPoint(fly.Position) - surface.center;
            float supportDepth = surface.transform.TransformVector(Vector3.forward * surface.size.z).magnitude;
            // The same central 70%-width, 1.7-unit strip is used by the visible stain.
            Vector3 normalized = new Vector3(p.x / surface.size.x, 0,
                p.z / surface.size.z * supportDepth / TraceDepth * .7f);
            float top = surface.bounds.max.y;
            if (!contact.Sample(normalized.x, normalized.z, fly.Position.y - top, observation.ground.point.y - top, valid)) return;
            feedback.Record("sugar_contact", sourceId);
        }
    }
}
