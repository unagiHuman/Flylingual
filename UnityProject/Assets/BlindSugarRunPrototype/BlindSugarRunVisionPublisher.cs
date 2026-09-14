using Flylingual.Conversation;
using UnityEngine;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Publishes a fresh local snapshot over the existing conversation connection.</summary>
    [DefaultExecutionOrder(420)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunVisionPublisher : MonoBehaviour
    {
        BlindSugarRunSession stage;
        BlindSugarRunLocalVision vision;
        ConversationSessionController conversation;
        long lastSample = -1;
        int generation = -1, epoch = -1;
        public long SentObservations { get; private set; }
        public float LastSentAt { get; private set; } = float.NegativeInfinity;

        void Awake() { stage = GetComponent<BlindSugarRunSession>(); }
        void Update()
        {
            if (stage == null || stage.State != BlindSugarRunSession.StageState.Playing) return;
            if (conversation == null) conversation = FindAnyObjectByType<ConversationSessionController>();
            if (vision == null) vision = FindAnyObjectByType<BlindSugarRunLocalVision>();
            if (conversation == null || vision == null || !vision.Fresh || vision.Facts == null) return;
            if (generation != conversation.ConversationGeneration || epoch != conversation.ControlEpoch)
            { lastSample = -1; generation = conversation.ConversationGeneration; epoch = conversation.ControlEpoch; }
            if (lastSample == vision.Sequence) return;
            if (!conversation.TrySendLocalVisualObservation(JsonUtility.ToJson(vision.Facts),
                Mathf.Max(0, (Time.unscaledTime - vision.SampledAt) * 1000f))) return;
            lastSample = vision.Sequence; LastSentAt = Time.unscaledTime; SentObservations++;
        }
    }
}
