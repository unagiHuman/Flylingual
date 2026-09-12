using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using UnityEngine;
using UnityEngine.SceneManagement;
using FlyBrainPoC;
using FlyLocomotionPoC;

namespace FlyVisualDemo
{
    public sealed class FixedDiagnosticReplay : FlyMotorSource
    {
        public BrainFrame Frame;
        public override string SourceName=>"FIXED_RECORDED_BRAINFRAME_DIAGNOSTIC";
        public override FlyMotorCommand GetMotorCommand()=>Frame==null?FlyMotorCommand.Stop:new FlyMotorCommand(Frame.motor.forward,Frame.motor.turn);
    }
    [DefaultExecutionOrder(10000)]
    public sealed class FixedPhysicsDiagnostic : MonoBehaviour
    {
        public static FixedPhysicsDiagnostic Current;
        public WindowsReplayDemo Demo;
        public string Trial;
        public float Elapsed;
        public bool Recording;
        StreamWriter legs,contacts,bodyLog,resetLog,rig,pairs,support;
        string output,fixtures;
        float started;
        int ticks;
        Vector3 rootPosition;
        Quaternion rootRotation;
        List<float> jointPositions;
        readonly List<string> cases=new List<string>();
        int caseIndex=-1;
        bool captured;
        FixedDiagnosticReplay source;
        FlyLocomotionConfig config;
        public static string F(float x)=>x.ToString("R",CultureInfo.InvariantCulture);
        public static T Read<T>(object o,string field)=>(T)o.GetType().GetField(field,BindingFlags.Instance|BindingFlags.NonPublic).GetValue(o);
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Boot()
        {
            if(!WindowsReplayDemo.Flag("-physicsDiagnostic"))return;
            var go=new GameObject("Fixed Physics Diagnostic");DontDestroyOnLoad(go);Current=go.AddComponent<FixedPhysicsDiagnostic>();
            SceneManager.sceneLoaded+=Current.Loaded;
        }
        void Awake()
        {
            output=WindowsReplayDemo.Argument("-demoOutput");fixtures=WindowsReplayDemo.Argument("-fixedFixtures");Directory.CreateDirectory(output);
            support=new StreamWriter(Path.Combine(output,"support.csv")){AutoFlush=true};
            support.WriteLine("trial,t,stage,leg,fixedTime,lastContactFixedTime,contactAge,source,holdTicks,fresh,commandStance,adhesionFixedTime,consumedStance,consumedContact,consumedHoldTicks,attached,normalForce,shearForce,nx,ny,nz,px,py,pz,velocityMeaning,targetCoxa,targetFemur,targetTibia");
            legs=new StreamWriter(Path.Combine(output,"legs.csv")){AutoFlush=true};
            contacts=new StreamWriter(Path.Combine(output,"contacts.csv")){AutoFlush=true};
            bodyLog=new StreamWriter(Path.Combine(output,"body.csv")){AutoFlush=true};
            resetLog=new StreamWriter(Path.Combine(output,"reset.jsonl")){AutoFlush=true};
            rig=new StreamWriter(Path.Combine(output,"rig.jsonl")){AutoFlush=true};
            pairs=new StreamWriter(Path.Combine(output,"pairs.csv")){AutoFlush=true};pairs.WriteLine("trial,t,owner,count,ix,iy,iz,sumPointIx,sumPointIy,sumPointIz");
            legs.WriteLine("trial,t,leg,rawF,rawT,cpgF,cpgT,phase,offset,stance,stanceDuration,scale,unclampedScale,scaleClamped,gaitDrive,strideAmplitude,coxaAmplitude,femurAmplitude,tibiaAmplitude,coxaRaw,coxaTarget,coxaActual,coxaVelocity,coxaForce,femurRaw,femurTarget,femurActual,tibiaRaw,tibiaTarget,tibiaActual,jointClamp,grounded,attached,normalForce,shearForce,overload,contactLost,swingDetach,adhesionFx,adhesionFy,adhesionFz,adhesionYawImpulse");
            contacts.WriteLine("trial,t,owner,leg,thisCollider,otherCollider,px,py,pz,nx,ny,nz,rawIx,rawIy,rawIz,ix,iy,iz,normalImpulse,tangentImpulse,rvx,rvy,rvz,yawImpulse");
            bodyLog.WriteLine("trial,t,x,y,z,yaw,vx,vy,vz,yawRate,comx,comy,comz,phase,fall,totalWorldLy,dampingYawImpulseEstimate");
            string batch=WindowsReplayDemo.Argument("-diagnosticBatch");
            if(batch=="steering")foreach(string a in new[]{"FORWARD_L","FORWARD_R"})foreach(int p in new[]{0,90})for(int n=0;n<3;n++)cases.Add(a+"_"+p+"_both_"+n);
            else if(batch=="phase")for(int p=0;p<360;p+=45)for(int n=0;n<3;n++)cases.Add("FORWARD_L_"+p+"_both_"+n);
            else if(batch=="ablation")foreach(string mode in new[]{"off","normal","shear","both"})for(int n=0;n<3;n++)cases.Add("FORWARD_L_90_"+mode+"_"+n);
            else if(batch=="repro")for(int n=0;n<5;n++)cases.Add("FORWARD_L_90_both_"+n);
            else foreach(string a in new[]{"TURN_L","FORWARD","FORWARD_L","TURN_R","FORWARD_R"})for(int n=0;n<5;n++)cases.Add(a+"_0_both_"+n);
            string initial=WindowsReplayDemo.Argument("-diagnosticInitial");
            if(File.Exists(initial)){var state=JsonUtility.FromJson<ResetRow>(File.ReadAllText(initial));rootPosition=state.position;rootRotation=state.rotation;jointPositions=state.jointPositions.ToList();captured=true;caseIndex=0;}
        }
        void Loaded(Scene scene,LoadSceneMode mode)
        {
            Demo=FindFirstObjectByType<WindowsReplayDemo>();
            if(Demo==null)return;
            Demo.client.Disconnect();Demo.client.enabled=false;
            Demo.enabled=false;
            foreach(var b in Demo.GetComponents<MonoBehaviour>())if(b!=Demo.controller && b!=Demo.replay && b!=Demo.live && b!=Demo.client)b.enabled=false;
            // The component only observes/sets explicit trial initial conditions. Production gait stays enabled.
            config=Read<FlyLocomotionConfig>(Demo.controller,"config");
            string amplitude=WindowsReplayDemo.Argument("-diagnosticCoxaAmplitude");
            string smoothing=WindowsReplayDemo.Argument("-diagnosticMotorSmoothing");
            if(!string.IsNullOrEmpty(amplitude)||!string.IsNullOrEmpty(smoothing))config=Instantiate(config);
            if(!string.IsNullOrEmpty(amplitude))config.coxaStrideAmplitudeDegrees=float.Parse(amplitude,CultureInfo.InvariantCulture);
            if(!string.IsNullOrEmpty(smoothing))config.motorSmoothingSeconds=float.Parse(smoothing,CultureInfo.InvariantCulture);
            source=Demo.gameObject.AddComponent<FixedDiagnosticReplay>();Demo.controller.Configure(Demo.body,source,config);
            Demo.controller.DiagnosticSeparateSteering=WindowsReplayDemo.Flag("-diagnosticSeparateSteering");
            if (float.TryParse(WindowsReplayDemo.Argument("-diagnosticJoinSeconds"), NumberStyles.Float, CultureInfo.InvariantCulture, out float joinSeconds)) Demo.controller.DiagnosticJoinSeconds=joinSeconds;
            Time.timeScale=5;Time.fixedDeltaTime=.02f;
            if(!captured){Recording=false;StartCoroutine(CaptureInitial());return;}
            SetupTrial();
        }
        IEnumerator CaptureInitial()
        {
            for(int i=0;i<100;i++)yield return new WaitForFixedUpdate();
            rootPosition=Demo.body.Position;rootRotation=Demo.body.Thorax.transform.rotation;
            jointPositions=new List<float>();Demo.body.Thorax.GetJointPositions(jointPositions);captured=true;
            string initial=WindowsReplayDemo.Argument("-diagnosticInitial");
            if(!string.IsNullOrEmpty(initial))File.WriteAllText(initial,JsonUtility.ToJson(new ResetRow{position=rootPosition,rotation=rootRotation,jointPositions=jointPositions.ToArray()}));
            caseIndex=0;SceneManager.LoadScene(SceneManager.GetActiveScene().path);
        }
        void SetupTrial()
        {
            Trial=cases[caseIndex];string[] split=Trial.Split('_');int n=split.Length;float phase=float.Parse(split[n-3],CultureInfo.InvariantCulture);string mode=split[n-2];string action=string.Join("_",split.Take(n-3));
            var root=Demo.body.Thorax;
            Vector3 position=rootPosition;Quaternion rotation=rootRotation;
            if(WindowsReplayDemo.Flag("-diagnosticRamp")){position=new Vector3(1.63960207f,.9579112f,3.019151f);rotation=Quaternion.Euler(0,40.508007f,0);}
            root.TeleportRoot(position,rotation);root.SetJointPositions(new List<float>(jointPositions));root.SetJointVelocities(jointPositions.Select(x=>0f).ToList());root.SetJointForces(jointPositions.Select(x=>0f).ToList());root.linearVelocity=Vector3.zero;root.angularVelocity=Vector3.zero;
            foreach(var rb in Demo.body.GetComponentsInChildren<Rigidbody>()){rb.linearVelocity=Vector3.zero;rb.angularVelocity=Vector3.zero;}
            foreach(var leg in Demo.body.Legs){leg.Coxa.SetTarget(0);leg.Femur.SetTarget(0);leg.Tibia.SetTarget(0);}
            var preset=Demo.gameplayPreset;
            Demo.controller.ConfigureFootAdhesion(mode!="off",mode=="shear"?0:preset.normalAdhesion,mode=="normal"?0:preset.shearAdhesion,preset.attachDelay,preset.detachThreshold);
            Demo.controller.Configure(Demo.body,source,config);Demo.controller.SetPhaseForDiagnostics(phase*Mathf.Deg2Rad);
            source.Frame=JsonUtility.FromJson<BrainFrame>(File.ReadAllText(Path.Combine(fixtures,action+".jsonl")));
            foreach(var a in Demo.body.GetComponentsInChildren<ArticulationBody>())
            {
                var observer=a.gameObject.AddComponent<DiagnosticContactObserver>();observer.Owner=a;
                if(caseIndex==0)rig.WriteLine(JsonUtility.ToJson(new RigRow(a)));
            }
            Physics.SyncTransforms();
            resetLog.WriteLine(JsonUtility.ToJson(new ResetRow{trial=Trial,position=position,rotation=rotation,linearVelocity=root.linearVelocity,angularVelocity=root.angularVelocity,jointPositions=GetPositions(root),jointVelocities=GetVelocities(root),phase=Demo.controller.Phase,attached=Demo.body.Legs.Count(l=>l.FootAdhesion.Attached)}));
            foreach (var leg in Demo.body.Legs)
                leg.FootAdhesion.DiagnosticDrivenByController=WindowsReplayDemo.Flag("-diagnosticOrderedAdhesion");
            Demo.controller.DiagnosticTargetObserved += ObserveTarget;
            ticks=0;started=Time.fixedTime;Elapsed=0;Recording=true;StartCoroutine(RecordTicks());
        }
        static float[] GetPositions(ArticulationBody root){var l=new List<float>();root.GetJointPositions(l);return l.ToArray();}
        static float[] GetVelocities(ArticulationBody root){var l=new List<float>();root.GetJointVelocities(l);return l.ToArray();}
        IEnumerator RecordTicks()
        {
            while(ticks<400)
            {
                yield return new WaitForFixedUpdate();ticks++;Elapsed=ticks*.02f;
                var b=Demo.body;var p=b.Position;var v=b.LinearVelocity;var com=b.Thorax.worldCenterOfMass;
                float ly=0,damping=0;foreach(var a in b.GetComponentsInChildren<ArticulationBody>()){var q=a.transform.rotation*a.inertiaTensorRotation;var spin=q*Vector3.Scale(a.inertiaTensor,Quaternion.Inverse(q)*a.angularVelocity);var orbital=Vector3.Cross(a.worldCenterOfMass,a.mass*a.linearVelocity);ly+=spin.y+orbital.y;damping-=(spin.y*a.angularDamping+orbital.y*a.linearDamping)*.02f;}
                bodyLog.WriteLine(string.Join(",",new[]{Trial,F(Elapsed),F(p.x),F(p.y),F(p.z),F(b.Thorax.transform.eulerAngles.y),F(v.x),F(v.y),F(v.z),F(b.AngularVelocity.y*Mathf.Rad2Deg),F(com.x),F(com.y),F(com.z),F(Demo.controller.Phase),p.y< -3?"1":"0",F(ly),F(damping)}));
                foreach(var leg in b.Legs)RecordLeg(leg);
            }
            Recording=false;Debug.Log("FIXED_DIAGNOSTIC_DONE "+Trial);
            if(++caseIndex<cases.Count)SceneManager.LoadScene(SceneManager.GetActiveScene().path);else {Close();Application.Quit();}
        }
        void ObserveTarget(FlyLeg leg, FlyLeg.LegDriveTarget target)
        {
            if (Recording) RecordSupport(leg,target.stance,target.angles,"BEFORE_APPLY");
        }
        void RecordSupport(FlyLeg leg,bool stance,Vector3 target,string stage)
        {
            var c=leg.FootContact;var a=leg.FootAdhesion;
            var n=c.SurfaceNormal;var p=c.SurfaceContactPoint;
            string age=float.IsNegativeInfinity(c.LastContactFixedTime)?"":F(Time.fixedTime-c.LastContactFixedTime);
            support.WriteLine(string.Join(",",new[]{Trial,F(Time.fixedTime-started),stage,leg.LegId,F(Time.fixedTime),F(c.LastContactFixedTime),age,c.ContactObservationSource,c.RemainingContactHoldTicks.ToString(),c.HasFreshSurfaceContact?"1":"0",stance?"1":"0",F(a.LastEvaluationFixedTime),a.LastEvaluatedStance?"1":"0",a.LastEvaluatedContact?"1":"0",a.LastEvaluatedHoldTicks.ToString(),a.Attached?"1":"0",F(a.NormalForceNewtons),F(a.ShearForceNewtons),F(n.x),F(n.y),F(n.z),F(p.x),F(p.y),F(p.z),c.ContactObservationSource=="ARTICULATION_OWNER"?"OWNER_LINEAR_NOT_POINT_RELATIVE":"COLLISION_RELATIVE_NOT_POINT_VERIFIED",F(target.x),F(target.y),F(target.z)}));
        }
        void RecordLeg(FlyLeg l)
        {
            var m=Demo.controller.CurrentMotor;float offset=l.Group==FlyLeg.TripodGroup.A?0:Mathf.PI;float ph=Demo.controller.EffectivePhase+offset;
            float scale=config.SideScale(l.LeftSide,Demo.controller.TrajectoryTurn),unclamped=l.LeftSide?1-config.turnSign*Demo.controller.TrajectoryTurn*config.steeringGain:1+config.turnSign*Demo.controller.TrajectoryTurn*config.steeringGain;
            RecordSupport(l,Mathf.Sin(ph)<=0,new Vector3(l.LastCorrectedCoxaTarget,l.LastCorrectedFemurTarget,l.LastCorrectedTibiaTarget),"POST_PHYSICS");
            float drive=Mathf.Max(Mathf.Abs(m.forward),Mathf.Abs(m.turn)*config.turnGaitContribution);
            var a=l.FootAdhesion;var force=a.NormalForceNewtons==0&&a.ShearForceNewtons==0?Vector3.zero:Read<Vector3>(a,"lastAdhesionForce");
            float yawImpulse=Vector3.Cross(l.FootContact.SurfaceContactPoint-Demo.body.Thorax.worldCenterOfMass,force*.02f).y;
            bool clamp=Mathf.Abs(l.LastCorrectedCoxaTarget-l.Coxa.Target)>.0001f||Mathf.Abs(l.LastCorrectedFemurTarget-l.Femur.Target)>.0001f||Mathf.Abs(l.LastCorrectedTibiaTarget-l.Tibia.Target)>.0001f;
            float Actual(FlyJoint j)=>j.Articulation.jointPosition[0]*Mathf.Rad2Deg;
            legs.WriteLine(string.Join(",",new[]{Trial,F(Elapsed),l.LegId,F(source.Frame.motor.forward),F(source.Frame.motor.turn),F(m.forward),F(m.turn),F(ph),F(offset),Mathf.Sin(ph)<=0?"1":"0",F(.5f/config.gaitFrequencyHz),F(scale),F(unclamped),Mathf.Abs(scale-unclamped)>.0001f?"1":"0",F(drive),F(config.coxaStrideAmplitudeDegrees*drive*scale),F(config.coxaStrideAmplitudeDegrees*drive*scale),F(config.femurLiftAmplitudeDegrees*drive),F(config.tibiaLiftAmplitudeDegrees*drive),F(l.LastCorrectedCoxaTarget),F(l.Coxa.Target),F(Actual(l.Coxa)),F(l.Coxa.Articulation.jointVelocity[0]),F(l.Coxa.Articulation.jointForce[0]),F(l.LastCorrectedFemurTarget),F(l.Femur.Target),F(Actual(l.Femur)),F(l.LastCorrectedTibiaTarget),F(l.Tibia.Target),F(Actual(l.Tibia)),clamp?"1":"0",l.IsGrounded?"1":"0",a.Attached?"1":"0",F(a.NormalForceNewtons),F(a.ShearForceNewtons),a.ShearOverloadDetachCount.ToString(),a.ContactLostDetachCount.ToString(),a.SwingDetachCount.ToString(),F(force.x),F(force.y),F(force.z),F(yawImpulse)}));
        }
        public void Contact(ArticulationBody owner,Collision collision)
        {
            if(!Recording)return;
            var sum=Vector3.zero;foreach(var cp in collision.contacts)sum+=cp.impulse;var total=collision.impulse;
            pairs.WriteLine(string.Join(",",new[]{Trial,F(Time.fixedTime-started),owner.name,collision.contactCount.ToString(),F(total.x),F(total.y),F(total.z),F(sum.x),F(sum.y),F(sum.z)}));
            foreach(var cp in collision.contacts)
            {
                bool first=cp.thisCollider!=null&&cp.thisCollider.attachedArticulationBody==owner;
                bool second=cp.otherCollider!=null&&cp.otherCollider.attachedArticulationBody==owner;
                if(!first&&!second)continue;
                Collider own=first?cp.thisCollider:cp.otherCollider,other=first?cp.otherCollider:cp.thisCollider;
                if(other.attachedArticulationBody!=null&&other.transform.IsChildOf(Demo.body.transform))continue;
                var leg=Demo.body.Legs.FirstOrDefault(l=>l.FootContact.GetComponent<Collider>()==own);
                string id=leg==null?"NON_FOOT":leg.LegId;
                var normal=first?cp.normal:-cp.normal;var raw=cp.impulse;
                // Orient receiver impulse by its repulsive normal component, independently of yaw.
                var impulse=Vector3.Dot(raw,normal)<0?-raw:raw;
                var tangent=impulse-Vector3.Project(impulse,normal);var point=cp.point;
                float yaw=Vector3.Cross(point-Demo.body.Thorax.worldCenterOfMass,impulse).y;
                var rv=collision.relativeVelocity;
                contacts.WriteLine(string.Join(",",new[]{Trial,F(Time.fixedTime-started),owner.name,id,own.name,other.name,F(point.x),F(point.y),F(point.z),F(normal.x),F(normal.y),F(normal.z),F(raw.x),F(raw.y),F(raw.z),F(impulse.x),F(impulse.y),F(impulse.z),F(Vector3.Dot(impulse,normal)),F(tangent.magnitude),F(rv.x),F(rv.y),F(rv.z),F(yaw)}));
            }
        }
        [Serializable]class ResetRow{public string trial;public Vector3 position,linearVelocity,angularVelocity;public Quaternion rotation;public float[] jointPositions,jointVelocities;public float phase;public int attached;}
        [Serializable]class RigRow
        {
            public string name;public Vector3 localPosition,com,anchor,parentAnchor;public Quaternion localRotation,anchorRotation,parentAnchorRotation;public float mass,lower,upper,stiffness,damping,forceLimit,maxVelocity;public string colliders;
            public RigRow(ArticulationBody a){name=a.name;localPosition=a.transform.localPosition;localRotation=a.transform.localRotation;com=a.centerOfMass;mass=a.mass;anchor=a.anchorPosition;parentAnchor=a.parentAnchorPosition;anchorRotation=a.anchorRotation;parentAnchorRotation=a.parentAnchorRotation;var d=a.xDrive;lower=d.lowerLimit;upper=d.upperLimit;stiffness=d.stiffness;damping=d.damping;forceLimit=d.forceLimit;maxVelocity=a.maxJointVelocity;colliders=string.Join(";",a.GetComponentsInChildren<Collider>().Where(c=>c.attachedArticulationBody==a).Select(c=>JsonUtility.ToJson(new ColliderRow(c))));}
        }
        [Serializable]class ColliderRow
        {
            public string name,type;public Vector3 position,scale,center,size;public Quaternion rotation;public float radius,height;public int direction;
            public ColliderRow(Collider c){name=c.name;type=c.GetType().Name;position=c.transform.localPosition;rotation=c.transform.localRotation;scale=c.transform.localScale;if(c is CapsuleCollider capsule){center=capsule.center;radius=capsule.radius;height=capsule.height;direction=capsule.direction;}else if(c is SphereCollider sphere){center=sphere.center;radius=sphere.radius;}else if(c is BoxCollider box){center=box.center;size=box.size;}}
        }
        void Close(){SceneManager.sceneLoaded-=Loaded;legs?.Dispose();contacts?.Dispose();bodyLog?.Dispose();resetLog?.Dispose();rig?.Dispose();pairs?.Dispose();support?.Dispose();}
        void OnDestroy(){if(Current==this)Close();}
    }
    public sealed class DiagnosticContactObserver : MonoBehaviour
    {
        public ArticulationBody Owner;
        void OnCollisionEnter(Collision c)=>FixedPhysicsDiagnostic.Current?.Contact(Owner,c);
        void OnCollisionStay(Collision c)=>FixedPhysicsDiagnostic.Current?.Contact(Owner,c);
    }
}
