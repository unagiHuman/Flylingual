using UnityEngine;

namespace FlyVisualDemo
{
    [CreateAssetMenu(menuName="FlyBrain/Gameplay Preset")]
    public sealed class FlyGameplayPreset : ScriptableObject
    {
        public float normalAdhesion=.12f;
        public float shearAdhesion=.10f;
        public float attachDelay=.02f;
        public float detachThreshold=1.25f;
        public float gaitFrequency=1.6f;
        public float steeringGain=1f;
        public float minimumSideScale=.15f;
        public Vector3 cameraOffset=new Vector3(7,7,-10);
        public float cameraLookAhead=2;
        public float cameraFov=43;
        public void Apply(WindowsReplayDemo demo)
        {
            var config=Instantiate(demo.body.Config);
            config.gaitFrequencyHz=gaitFrequency;config.steeringGain=steeringGain;config.minimumSideScale=minimumSideScale;
            demo.controller.Configure(demo.body,demo.replay,config);
            demo.controller.ConfigureFootAdhesion(true,normalAdhesion,shearAdhesion,attachDelay,detachThreshold);
            if(demo.view!=null) demo.view.fieldOfView=cameraFov;
        }
    }
}
