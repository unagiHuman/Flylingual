using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyFootPadCollisionRelay : MonoBehaviour
    {
        [SerializeField] private FlyFootContact footContact;

        public void Configure(FlyFootContact contact)
        {
            footContact = contact;
        }

        private void OnCollisionEnter(Collision collision)
        {
            if (footContact != null) footContact.CaptureFromArticulationOwner(collision, true);
        }

        private void OnCollisionStay(Collision collision)
        {
            if (footContact != null) footContact.CaptureFromArticulationOwner(collision, false);
        }

        private void OnCollisionExit(Collision collision)
        {
            if (footContact != null) footContact.ReleaseFromArticulationOwner(collision);
        }
    }
}
