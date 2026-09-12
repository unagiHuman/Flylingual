using System.Collections.Generic;
using FlyVisualDemo;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Display-only colour pulse. No transform, collider, joint, or motor value is changed.</summary>
    public sealed class NativeConversationReaction : MonoBehaviour
    {
        sealed class Target
        {
            public Renderer renderer;
            public MaterialPropertyBlock original;
            public Color baseColor;
            public int colorProperty;
        }

        ConversationSessionController conversation;
        readonly List<Target> targets = new List<Target>();
        MaterialPropertyBlock working;
        static readonly int BaseColor = Shader.PropertyToID("_BaseColor");
        static readonly int ColorProperty = Shader.PropertyToID("_Color");

        void Awake()
        {
            working = new MaterialPropertyBlock();
            conversation = GetComponent<ConversationSessionController>();
            var demo = FindFirstObjectByType<WindowsReplayDemo>();
            if (demo == null || demo.visualRig == null) return;
            foreach (Renderer renderer in demo.visualRig.GetComponentsInChildren<Renderer>(true))
            {
                Material material = renderer.sharedMaterial;
                if (material == null) continue;
                int property = material.HasProperty(BaseColor) ? BaseColor : material.HasProperty(ColorProperty) ? ColorProperty : 0;
                if (property == 0) continue;
                var original = new MaterialPropertyBlock();
                renderer.GetPropertyBlock(original);
                targets.Add(new Target { renderer = renderer, original = original, baseColor = material.GetColor(property), colorProperty = property });
            }
        }

        void LateUpdate()
        {
            if (conversation == null) return;
            float strength = Mathf.Clamp01(conversation.InputRms * 8f);
            if (conversation.ReplyPlaying) strength = Mathf.Max(strength, .2f + .12f * Mathf.Sin(Time.unscaledTime * 8f));
            foreach (Target target in targets)
            {
                if (target.renderer == null) continue;
                // Read the current block every frame so unrelated visual components retain their properties.
                target.renderer.GetPropertyBlock(working);
                Color tint = Color.Lerp(target.baseColor, new Color(.32f, .75f, 1f, target.baseColor.a), strength * .18f);
                working.SetColor(target.colorProperty, tint);
                target.renderer.SetPropertyBlock(working);
            }
        }

        void OnDisable()
        {
            foreach (Target target in targets)
                if (target.renderer != null) target.renderer.SetPropertyBlock(target.original);
        }
    }
}
