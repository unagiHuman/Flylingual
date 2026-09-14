Shader "Flylingual/IdleSwatter"
{
    Properties
    {
        _Color ("Color", Color) = (1, 1, 1, 1)
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" }
        Pass
        {
            Tags { "LightMode" = "SRPDefaultUnlit" }
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            struct VertexInput { float4 vertex : POSITION; };
            struct VertexOutput { float4 position : SV_POSITION; };
            float4 _Color;

            VertexOutput vert(VertexInput input)
            {
                VertexOutput output;
                output.position = UnityObjectToClipPos(input.vertex);
                return output;
            }

            float4 frag(VertexOutput input) : SV_Target { return _Color; }
            ENDHLSL
        }
    }
}
