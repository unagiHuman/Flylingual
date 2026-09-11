using System;
using UnityEngine;

namespace FlyVisualDemo
{
    // World-space rest offsets account for different pivot axes and hierarchies.
    public sealed class VisualRigMapper : MonoBehaviour
    {
        [Serializable] public class Binding
        {
            public string joint;
            public Transform physics;
            public Transform visual;
            public Transform physicsTip;
            public Vector3 positionOffset;
            public Quaternion rotationOffset = Quaternion.identity;
            public Vector3 scaleRatio = Vector3.one;
        }
        public Binding[] bindings = Array.Empty<Binding>();
        public float MaximumEndpointError { get; private set; }
        public void Calibrate()
        {
            foreach (var b in bindings)
            {
                if (b.physics == null || b.visual == null) throw new InvalidOperationException("Missing visual mapping: " + b.joint);
                if (b.physicsTip != null) continue; // Segment endpoints resolve nonuniform/sheared parent scale exactly.
                b.positionOffset = b.physics.InverseTransformPoint(b.visual.position);
                b.rotationOffset = Quaternion.Inverse(b.physics.rotation) * b.visual.rotation;
                Vector3 s = b.physics.lossyScale;
                b.scaleRatio = new Vector3(b.visual.lossyScale.x / s.x, b.visual.lossyScale.y / s.y, b.visual.lossyScale.z / s.z);
            }
        }
        void Awake()
        {
            foreach (var b in bindings)
                if (b.physics == null || b.visual == null) { Debug.LogError("Missing visual mapping: " + b.joint, this); enabled = false; }
            if (GetComponentsInChildren<Collider>(true).Length + GetComponentsInChildren<Rigidbody>(true).Length + GetComponentsInChildren<ArticulationBody>(true).Length != 0)
            { Debug.LogError("VisualRig contains a physics component", this); enabled = false; }
        }
        void LateUpdate()
        {
            foreach (var b in bindings)
            {
                if(b.physicsTip!=null)
                {
                    Vector3 start=b.physics.TransformPoint(b.positionOffset);
                    Vector3 axis=b.physicsTip.position-start;
                    if(axis.sqrMagnitude<1e-10f) continue;
                    b.visual.SetPositionAndRotation(start,Quaternion.LookRotation(axis,b.physics.rotation*Vector3.up));
                    b.visual.localScale=new Vector3(1,1,axis.magnitude);
                    MaximumEndpointError=Mathf.Max(MaximumEndpointError,Vector3.Distance(b.visual.TransformPoint(Vector3.forward),b.physicsTip.position));
                    continue;
                }
                b.visual.SetPositionAndRotation(b.physics.TransformPoint(b.positionOffset), b.physics.rotation * b.rotationOffset);
                b.visual.localScale = Vector3.Scale(b.physics.lossyScale, b.scaleRatio); // VisualRig parent has unit scale.
            }
        }
    }
}
