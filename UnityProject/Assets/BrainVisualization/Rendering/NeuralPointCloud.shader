Shader "FlyBrain/Neural Point Cloud"
{
    Properties
    {
        _PointSize ("Point size", Float) = 0.016
        _RestingBrightness ("Resting brightness", Range(0, 1)) = 0.5
        _AfterglowSeconds ("Spike afterglow seconds", Float) = 0.25
        _DisplayGain ("Display gain", Range(0, 4)) = 1
        _SpikeScale ("Spike scale", Range(1, 1.5)) = 1.5
        _SpikeHaloScale ("Spike halo scale", Range(1, 3)) = 2.4
        _SpikeGlowGain ("Spike glow gain", Range(0.25, 4)) = 2
        _ShowMembranePotential ("Show membrane potential", Float) = 0
        [HideInInspector] _DisplayTime ("Unscaled display time", Float) = 0
    }
    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "Queue" = "Transparent" "RenderType" = "Transparent" }
        Pass
        {
            Name "NeuralPoints"
            Tags { "LightMode" = "UniversalForward" }
            Blend One OneMinusSrcAlpha
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma target 3.5
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float _PointSize;
                float _RestingBrightness;
                float _AfterglowSeconds;
                float _DisplayGain;
                float _SpikeScale;
                float _SpikeHaloScale;
                float _SpikeGlowGain;
                float _ShowMembranePotential;
                float _DisplayTime;
            CBUFFER_END

            struct Attributes
            {
                float3 positionOS : POSITION;
                float2 corner : TEXCOORD0;
                float2 spikeTime : TEXCOORD1;
                float4 activity : COLOR;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 corner : TEXCOORD0;
                float4 activity : TEXCOORD1;
                float spikeAge : TEXCOORD2;
                float viewDepth : TEXCOORD3;
                float coreRadiusSquared : TEXCOORD4;
            };

            Varyings Vert(Attributes input)
            {
                Varyings output;
                float3 centerWS = TransformObjectToWorld(input.positionOS);
                float rate = saturate(input.activity.r * _DisplayGain) * input.activity.b;
                float spikeAge = _DisplayTime - input.spikeTime.x;
                float decay = saturate(1.0 - max(0.0, spikeAge) / max(0.01, _AfterglowSeconds));
                float perceptualRate = 1.0 - exp2(-rate * _SpikeGlowGain);
                float afterglow = perceptualRate * decay;
                float flash = perceptualRate * saturate(1.0 - max(0.0, spikeAge) / max(0.02, _AfterglowSeconds * 0.32));
                float haloStrength = saturate(afterglow * 0.82 + flash * 0.72);
                float3 viewRight = normalize(mul((float3x3)UNITY_MATRIX_I_V, float3(1.0, 0.0, 0.0)));
                float3 viewUp = normalize(mul((float3x3)UNITY_MATRIX_I_V, float3(0.0, 1.0, 0.0)));
                float haloScale = lerp(1.0, _SpikeHaloScale, haloStrength);
                float size = _PointSize * haloScale;
                float3 billboardWS = centerWS + (viewRight * input.corner.x + viewUp * input.corner.y) * (size * 0.5);
                output.positionCS = TransformWorldToHClip(billboardWS);
                output.corner = input.corner;
                output.activity = input.activity;
                output.spikeAge = spikeAge;
                output.viewDepth = max(0.0, -TransformWorldToView(centerWS).z);
                float coreRadius = lerp(1.0, _SpikeScale, flash) / haloScale;
                output.coreRadiusSquared = coreRadius * coreRadius;
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                float radiusSquared = dot(input.corner, input.corner);
                float softMask = saturate(1.0 - radiusSquared);
                softMask *= softMask;
                clip(softMask - 0.002);

                float observed = input.activity.b;
                float rate = saturate(input.activity.r * _DisplayGain) * observed;
                float decay = saturate(1.0 - max(0.0, input.spikeAge) / max(0.01, _AfterglowSeconds));
                float perceptualRate = 1.0 - exp2(-rate * _SpikeGlowGain);
                float afterglow = perceptualRate * decay;
                float flash = perceptualRate * saturate(1.0 - max(0.0, input.spikeAge) / max(0.02, _AfterglowSeconds * 0.32));
                float haloStrength = saturate(afterglow * 0.82 + flash * 0.72);
                float deltaKnown = input.activity.a;
                float deltaSigned = (input.activity.g * 2.0 - 1.0);
                float deltaMagnitude = abs(deltaSigned);
                float membraneAmount = _ShowMembranePotential * deltaKnown * deltaMagnitude;

                // Unobserved anatomy remains light gray; measured zero is deliberately whiter.
                float3 anatomy = lerp(float3(0.56, 0.60, 0.64), float3(1.0, 0.98, 0.92), observed) * _RestingBrightness;
                float3 membrane = deltaSigned >= 0.0 ? float3(0.42, 0.80, 0.92) : float3(0.62, 0.48, 0.82);
                float3 measured = lerp(anatomy, membrane, membraneAmount * 0.42);
                // Gaussian falloff reaches zero at the billboard edge without a bright disc rim.
                float haloMask = saturate((exp2(-4.0 * radiusSquared) - 0.0625) / 0.9375);
                float core = 1.0 - smoothstep(input.coreRadiusSquared * 0.18, input.coreRadiusSquared, radiusSquared);
                float3 spike = lerp(float3(1.0, 0.055, 0.008), float3(1.0, 0.30, 0.025), perceptualRate);
                float coreGlow = core * (flash * 1.15 + afterglow * 0.38);
                float3 color = lerp(measured, spike, haloMask * haloStrength * 0.42);

                // A mild depth term preserves the atlas volume without hiding its far anatomy.
                float depthAttenuation = lerp(1.0, 0.78, saturate(input.viewDepth / 8.0));
                // Expanding the light must not expand the underlying gray anatomy.
                float haloScale = lerp(1.0, _SpikeHaloScale, haloStrength);
                float anatomyMask = saturate(1.0 - radiusSquared * haloScale * haloScale);
                float alpha = anatomyMask * anatomyMask * lerp(0.11, 0.18, observed);
                alpha = saturate(alpha + haloMask * haloStrength * 0.14 + coreGlow * 0.10) * depthAttenuation;

                // These additions are intentional LDR emission: a low-alpha halo lights the
                // background without global Bloom, while every real nonzero aggregate gets a warm core.
                float3 haloEmission = float3(1.0, 0.075, 0.008) * haloMask * haloStrength * 0.82;
                float3 coreEmission = float3(1.0, 0.86, 0.58) * coreGlow * 1.18;
                return half4(color * alpha + haloEmission + coreEmission, alpha);
            }
            ENDHLSL
        }
    }
}
