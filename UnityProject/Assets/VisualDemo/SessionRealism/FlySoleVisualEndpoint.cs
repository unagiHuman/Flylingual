using FlyLocomotionPoC;
using UnityEngine;

namespace FlyVisualDemo
{
    // Visual endpoint only: follows the physical FootPad surface, including
    // during swing. No ground raycast, joint write or force is applied here.
    [DefaultExecutionOrder(-50)]
    public sealed class FlySoleVisualEndpoint : MonoBehaviour
    {
        public SphereCollider foot;
        public FlyFootContact contact;
        public Transform thorax;
        public Vector3 SurfacePoint { get; private set; }

        public void Refresh()
        {
            if (foot == null) return;
            Vector3 normal = contact != null && contact.HasFreshSurfaceContact
                ? contact.SurfaceNormal : thorax == null ? Vector3.up : thorax.up;
            if (normal.sqrMagnitude < .5f) normal = Vector3.up;
            normal.Normalize();
            Vector3 scale = foot.transform.lossyScale;
            float radius = foot.radius * Mathf.Max(Mathf.Abs(scale.x), Mathf.Abs(scale.y), Mathf.Abs(scale.z));
            // Runtime bounds come from the actual PhysX sphere, avoiding an
            // Editor approximation under the rig's nonuniform parent scale.
            Vector3 center = foot.transform.TransformPoint(foot.center);
            if (Application.isPlaying && foot.enabled)
            {
                Bounds bounds = foot.bounds;
                SurfacePoint = foot.ClosestPoint(bounds.center - normal * (bounds.extents.magnitude + .01f));
                transform.position = SurfacePoint;
                return;
            }
            SurfacePoint = center - normal * radius;
            transform.position = SurfacePoint;
        }

        void LateUpdate() => Refresh();
    }
}
