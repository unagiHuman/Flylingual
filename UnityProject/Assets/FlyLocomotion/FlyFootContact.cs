using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyFootContact : MonoBehaviour
    {
        [SerializeField] private string legId;
        [SerializeField] private Collider footCollider;
        [SerializeField] private ArticulationBody expectedArticulationBody;

        private bool hasSurfaceContact;
        private Vector3 surfaceContactPoint;
        private Vector3 surfaceNormal;
        private Vector3 surfaceRelativeVelocity;
        private string otherColliderName = string.Empty;
        private int enterCount;
        private int stayCount;
        private int exitCount;
        private int contactHoldTicks;
        public int RemainingContactHoldTicks => contactHoldTicks;
        public float LastContactFixedTime { get; private set; } = float.NegativeInfinity;
        public string ContactObservationSource { get; private set; } = "NONE";

        public string LegId => legId;
        public bool TouchingGround => HasFreshSurfaceContact;
        public Vector3 ProbePosition => transform.position;
        public bool HasFreshSurfaceContact => hasSurfaceContact && contactHoldTicks > 0;
        public Vector3 SurfaceContactPoint => surfaceContactPoint;
        public Vector3 SurfaceNormal => surfaceNormal;
        public Vector3 SurfaceRelativeVelocity => surfaceRelativeVelocity;
        public string FootColliderEntityId => footCollider == null ? string.Empty : footCollider.GetEntityId().ToString();
        public string OtherColliderName => otherColliderName;
        public int EnterCount => enterCount;
        public int StayCount => stayCount;
        public int ExitCount => exitCount;
        public bool AttachedArticulationBodyMatches => footCollider != null &&
                                                       footCollider.attachedArticulationBody == expectedArticulationBody;

        public void Configure(string id, Collider collider, ArticulationBody articulationBody)
        {
            legId = id;
            footCollider = collider;
            expectedArticulationBody = articulationBody;
        }

        public void AdvanceAdhesionTick()
        {
            if (contactHoldTicks > 0) contactHoldTicks--;
            if (contactHoldTicks == 0) hasSurfaceContact = false;
        }

        private void OnCollisionEnter(Collision collision)
        {
            if (TryCapture(collision)) enterCount++;
        }

        private void OnCollisionStay(Collision collision)
        {
            if (TryCapture(collision)) stayCount++;
        }

        private void OnCollisionExit(Collision collision)
        {
            Collider other = GetOtherCollider(collision);
            if (other == null || !IsAdhesiveSurface(other)) return;
            exitCount++;
            // Freshness of the last FootPad contact owns contact loss because a
            // compound articulation can emit sibling-collider exits here.
        }

        private bool TryCapture(Collision collision)
        {
            Collider other = GetOtherCollider(collision);
            if (other == null || !IsAdhesiveSurface(other) || collision.contactCount == 0) return false;

            ContactPoint contact = collision.GetContact(0);
            LastContactFixedTime = Time.fixedTime;
            ContactObservationSource = "DIRECT_COLLISION";
            hasSurfaceContact = true;
            contactHoldTicks = 3;
            surfaceContactPoint = contact.point;
            surfaceNormal = contact.normal.normalized;
            surfaceRelativeVelocity = collision.relativeVelocity;
            otherColliderName = other.name;
            return true;
        }

        public void CaptureFromArticulationOwner(Collision collision, bool entered)
        {
            if (collision == null) return;
            for (int i = 0; i < collision.contactCount; i++)
            {
                ContactPoint contact = collision.GetContact(i);
                bool footIsFirst = contact.thisCollider == footCollider;
                bool footIsSecond = contact.otherCollider == footCollider;
                if (!footIsFirst && !footIsSecond) continue;

                Collider other = footIsFirst ? contact.otherCollider : contact.thisCollider;
                if (other == null || !IsAdhesiveSurface(other)) continue;

                LastContactFixedTime = Time.fixedTime;
                ContactObservationSource = "ARTICULATION_OWNER";
                hasSurfaceContact = true;
                contactHoldTicks = 3;
                surfaceContactPoint = contact.point;
                surfaceNormal = (footIsFirst ? contact.normal : -contact.normal).normalized;
                surfaceRelativeVelocity = expectedArticulationBody == null
                    ? collision.relativeVelocity
                    : expectedArticulationBody.linearVelocity;
                otherColliderName = other.name;
                if (entered) enterCount++;
                else stayCount++;
                return;
            }
        }

        public void ReleaseFromArticulationOwner(Collision collision)
        {
            // Compound ArticulationBody callbacks include exits from sibling colliders.
            // Contact loss is therefore determined by last FootPad contact freshness.
            exitCount++;
        }

        private Collider GetOtherCollider(Collision collision)
        {
            if (collision == null) return null;
            return collision.collider != footCollider ? collision.collider : null;
        }

        private static bool IsAdhesiveSurface(Collider collider)
        {
            return collider.GetComponentInParent<FlyGroundMarker>() != null ||
                   collider.GetComponentInParent<FlyStepObstacle>() != null;
        }
    }
}
