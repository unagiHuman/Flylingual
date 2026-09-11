using UnityEngine;

namespace FlyVisualDemo
{
    // Subtle display-only vibration; no aerodynamic force or physics authority.
    public sealed class FlyWingBuzz : MonoBehaviour
    {
        Transform[] wings;
        Quaternion[] rest;
        void Awake()
        {
            var found=new System.Collections.Generic.List<Transform>();
            foreach(var renderer in GetComponentsInChildren<Renderer>())
                if(renderer.name.Contains("WingMembrane") || renderer.name.Contains("WingVein"))found.Add(renderer.transform);
            wings=found.ToArray();rest=new Quaternion[wings.Length];
            for(int i=0;i<wings.Length;i++)rest[i]=wings[i].localRotation;
        }
        void LateUpdate()
        {
            float angle=Mathf.Sin(Time.time*2*Mathf.PI*17)*.65f;
            for(int i=0;i<wings.Length;i++)wings[i].localRotation=rest[i]*Quaternion.Euler(angle,0,0);
        }
    }
}
