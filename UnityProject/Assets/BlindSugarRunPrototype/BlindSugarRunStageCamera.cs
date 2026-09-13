using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Stage framing only. Does not change body, input, or connection state.</summary>
    [DefaultExecutionOrder(200)]
    public sealed class BlindSugarRunStageCamera : MonoBehaviour
    {
        public Transform follow;
        public Camera stageCamera;
        public Vector3 offset = new Vector3(14f, 20f, -26f);
        public Vector3 lookAhead = new Vector3(0f, 0f, 9f);

        void Start()
        {
            Debug.Log("BLIND_SUGAR_RUN_STARTED scene=" + gameObject.scene.name +
                " fly=" + (follow != null ? follow.name : "missing") + " control=existing_native");
        }

        void LateUpdate()
        {
            if (follow == null || stageCamera == null) return;
            stageCamera.transform.position = follow.position + offset;
            stageCamera.transform.LookAt(follow.position + lookAhead);
        }
    }
}
