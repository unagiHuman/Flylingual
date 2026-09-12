Shader "FlyBrain/Neural Point Cloud"
{
    Properties
    {
        _PointSize ("Point size", Float) = 0.012
        _RestingBrightness ("Resting brightness", Range(0, 1)) = 0.16
        _AfterglowSeconds ("Spike afterglow seconds", Float) = 0.18
        _DisplayGain ("Display gain", Range(0, 4)) = 1
        [HideInInspector] _DisplayTime ("Unscaled display time", Float) = 0
    }
    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "Queue" = "Transparent" "RenderType" = "Transparent" }
        Pass
        {
            Name "NeuralPoints"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha One
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
            };

            Varyings Vert(Attributes input)
            {
                Varyings output;
                float3 centerWS = TransformObjectToWorld(input.positionOS);
                float3 viewRight = normalize(mul((float3x3)UNITY_MATRIX_I_V, float3(1.0, 0.0, 0.0)));
                float3 viewUp = normalize(mul((float3x3)UNITY_MATRIX_I_V, float3(0.0, 1.0, 0.0)));
                float3 billboardWS = centerWS + (viewRight * input.corner.x + viewUp * input.corner.y) * (_PointSize * 0.5);
                output.positionCS = TransformWorldToHClip(billboardWS);
                output.corner = input.corner;
                output.activity = input.activity;
                output.spikeAge = _DisplayTime - input.spikeTime.x;
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
                float afterglow = rate * saturate(1.0 - max(0.0, input.spikeAge) / max(0.01, _AfterglowSeconds));
                float deltaKnown = observed * input.activity.a;
                float deltaSigned = (input.activity.g * 2.0 - 1.0);
                float deltaMagnitude = abs(deltaSigned);

                float3 silhouette = float3(0.03, 0.25, 0.90) * _RestingBrightness;
                float3 membrane = deltaSigned >= 0.0 ? float3(0.0, 0.34, 0.72) : float3(0.08, 0.12, 0.32);
                float3 measured = lerp(silhouette, membrane, deltaKnown * deltaMagnitude * 0.62);
                float3 spike = lerp(float3(1.0, 0.32, 0.035), float3(1.0, 0.92, 0.72), rate);
                float core = smoothstep(0.75, 0.0, radiusSquared);
                float3 color = measured + spike * afterglow * (0.75 + core * 1.8);
                float alpha = softMask * (0.22 + observed * 0.14 + afterglow * 0.82);
                return half4(color * softMask, alpha);
            }
            ENDHLSL
        }
    }
}
