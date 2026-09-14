using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Optional local-only label for a collider that the fly can actually hit.</summary>
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunVisibleObject : MonoBehaviour
    {
        [Tooltip("One of desk, ruler, book, plate, sugar, path, obstacle. Empty is unknown.")]
        public string kind = "unknown";
        public bool hasVisibleHeading;
        public Vector3 localHeading = Vector3.forward;
    }
}
