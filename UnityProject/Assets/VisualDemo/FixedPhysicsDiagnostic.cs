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
        StreamWriter legs,contacts,bodyLog,resetLog,rig,pairs,support,liveLog,wire,motorUse;
        readonly object wireLock=new object();
        StreamWriter goalLog;
        Vector3 goalPosition;
        float nextGoalCommand, goalStable;
        float goalCommandTime, predictedStopSeconds=2.5f, observedYaw, observedYawTime, filteredYawRate;
        bool PredictiveGoal => WindowsReplayDemo.Flag("-diagnosticPredictiveGoal");
        readonly Queue<Vector4> goalPoses=new Queue<Vector4>();
        string goalAction="STOP";
        bool goalPassed;
        bool IsGoal => !string.IsNullOrEmpty(WindowsReplayDemo.Argument("-diagnosticGoal"));
        float nextCapture;
        int captureIndex;
        void Update()
        {
            if(Recording&&IsGoal)UpdateGoal();
            if(!Recording || !IsLive || !WindowsReplayDemo.Flag("-diagnosticCapture"))return;
            if(Time.realtimeSinceStartup<nextCapture)return;
            nextCapture=Time.realtimeSinceStartup+.1f;
            ScreenCapture.CaptureScreenshot(Path.Combine(output,"capture-"+(captureIndex++).ToString("D4")+".png"));
        }
        bool IsLive => WindowsReplayDemo.Flag("-diagnosticWindowsLive");
        BrainFrame ObservedFrame => IsLive ? Demo.client.LatestBrainFrame : source.Frame;
        void Received(string line){lock(wireLock)wire?.WriteLine("{\"utc\":\""+DateTime.UtcNow.ToString("o")+"\",\"direction\":\"receive\",\"message\":"+line+"}");}
        void Sent(string line){lock(wireLock)wire?.WriteLine("{\"utc\":\""+DateTime.UtcNow.ToString("o")+"\",\"direction\":\"send\",\"message\":"+line+"}");}
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
            if(IsLive){
                liveLog=new StreamWriter(Path.Combine(output,"live.csv")){AutoFlush=true};
                liveLog.WriteLine("t,sequence,action,forward,turn,backend,ready,age,error,utc");
                motorUse=new StreamWriter(Path.Combine(output,"motor-use.csv")){AutoFlush=true};
                motorUse.WriteLine("t,utc,sequence,action,forward,turn,age,fresh,cpgForward,cpgTurn,phase");
                wire=new StreamWriter(Path.Combine(output,"live-wire.jsonl")){AutoFlush=true};
            }
            string batch=WindowsReplayDemo.Argument("-diagnosticBatch");
            if(IsLive){
                string action=WindowsReplayDemo.Argument("-diagnosticLiveAction");
                if(string.IsNullOrEmpty(action))action="FORWARD_L";
                if(action!="FORWARD_L"&&action!="FORWARD_R")throw new ArgumentException("Expected FORWARD_L or FORWARD_R");
                cases.Add(action+"_90_both_0");
            }
            else if(batch=="steering")foreach(string a in new[]{"FORWARD_L","FORWARD_R"})foreach(int p in new[]{0,90})for(int n=0;n<3;n++)cases.Add(a+"_"+p+"_both_"+n);
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
            if(!IsLive) source=Demo.gameObject.AddComponent<FixedDiagnosticReplay>();
            Demo.controller.Configure(Demo.body,IsLive?(FlyMotorSource)Demo.live:source,config);
            Demo.controller.DiagnosticSeparateSteering=WindowsReplayDemo.Flag("-diagnosticSeparateSteering");
            if (float.TryParse(WindowsReplayDemo.Argument("-diagnosticJoinSeconds"), NumberStyles.Float, CultureInfo.InvariantCulture, out float joinSeconds)) Demo.controller.DiagnosticJoinSeconds=joinSeconds;
            Time.timeScale=IsLive?0:5;Time.fixedDeltaTime=.02f;
            if(IsLive){
                if(!captured)throw new InvalidOperationException("Live diagnostic requires local saved initial state");
                StartCoroutine(ConnectWindows());return;
            }
            if(!captured){Recording=false;StartCoroutine(CaptureInitial());return;}
            SetupTrial();
        }
        IEnumerator ConnectWindows()
        {
            Demo.live.Configure(Demo.client);
            Demo.client.ConfigureEndpoint("127.0.0.1",18766,false);
            Demo.client.ReceivedLine+=Received;Demo.client.SentLine+=Sent;
            Demo.client.Connect();float deadline=Time.realtimeSinceStartup+30;bool sent=false;
            while(Time.realtimeSinceStartup<deadline){
                if(!string.IsNullOrEmpty(Demo.client.LastError)){Debug.LogError("LIVE_DIAGNOSTIC "+Demo.client.LastError);Application.Quit(2);yield break;}
                if(Demo.client.ConnectionState=="CONNECTED"&&!sent){Demo.client.SetAction("STOP",true);sent=true;}
                if(sent&&Demo.client.TryGetLatestFrame(out var f,out double age)&&f.appliedRequestId>0&&f.requestedAction=="STOP"&&f.metadata.backendId=="MALECNS_EXPERIMENTAL"&&Mathf.Abs(f.motor.forward)<.01f&&Mathf.Abs(f.motor.turn)<.01f&&age<.75){SetupTrial();yield break;}
                yield return null;
            }
            Debug.LogError("LIVE_DIAGNOSTIC initial STOP timeout");Application.Quit(2);
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
            Demo.controller.Configure(Demo.body,IsLive?(FlyMotorSource)Demo.live:source,config);Demo.controller.SetPhaseForDiagnostics(phase*Mathf.Deg2Rad);
            if(!IsLive)source.Frame=JsonUtility.FromJson<BrainFrame>(File.ReadAllText(Path.Combine(fixtures,action+".jsonl")));
            else {
                string excluded=WindowsReplayDemo.Argument("-diagnosticIgnoreTibia");
                var mappings=new List<string>();
                if(!string.IsNullOrEmpty(excluded)&&excluded!="NONE"){
                    var leg=Demo.body.Legs.Single(l=>l.LegId==excluded);
                    var environment=FindObjectsByType<Collider>(FindObjectsSortMode.None).Where(c=>!c.transform.IsChildOf(Demo.body.transform)&&(c.GetComponentInParent<FlyGroundMarker>()!=null||c.GetComponentInParent<FlyStepObstacle>()!=null)).ToArray();
                    foreach(var tibia in leg.Tibia.Articulation.GetComponents<Collider>()){
                        if(tibia==leg.FootContact.GetComponent<Collider>())throw new InvalidOperationException("Cannot exclude FootPad");
                        foreach(var surface in environment){Physics.IgnoreCollision(tibia,surface,true);mappings.Add(tibia.name+" -> "+surface.name);}
                    }
                    if(mappings.Count==0)throw new InvalidOperationException("No Tibia/environment pairs found");
                }
                File.WriteAllLines(Path.Combine(output,"ignored-collision-pairs.txt"),mappings);
                if(IsGoal){
                    string direction=WindowsReplayDemo.Argument("-diagnosticGoal");
                    Vector3 front=Vector3.ProjectOnPlane(root.transform.forward,Vector3.up).normalized;
                    Vector3 right=Vector3.Cross(Vector3.up,front);
                    Vector3 offset=direction=="front"?front:direction=="back"?-front:direction=="left"?-right:right;
                    goalPosition=position+offset*1.5f;
                    var floor=FindObjectsByType<Collider>(FindObjectsSortMode.None).First(c=>c.name=="Ground");
                    if(!floor.bounds.Contains(new Vector3(goalPosition.x,floor.bounds.center.y,goalPosition.z)))throw new InvalidOperationException("Goal outside floor");
                    foreach(var c in FindObjectsByType<Collider>(FindObjectsSortMode.None))
                        if(!c.transform.IsChildOf(Demo.body.transform)&&c!=floor)c.enabled=false;
                    var marker=GameObject.CreatePrimitive(PrimitiveType.Sphere);marker.name="Diagnostic goal";
                    Destroy(marker.GetComponent<Collider>());marker.transform.position=new Vector3(goalPosition.x,.08f,goalPosition.z);marker.transform.localScale=Vector3.one*.3f;marker.GetComponent<Renderer>().material.color=Color.green;
                    goalLog=new StreamWriter(Path.Combine(output,"goal.csv")){AutoFlush=true};
                    goalLog.WriteLine("t,distance,headingError,action,x,z,targetX,targetZ,speed,stable,stopHorizon,stopDistance,yawRate");
                    File.WriteAllText(Path.Combine(output,"goal-config.json"),JsonUtility.ToJson(new GoalConfig{direction=direction,target=goalPosition,start=position}));
                    goalAction="STOP";nextGoalCommand=0;Demo.client.SetAction("STOP",true);
                } else Demo.client.SetAction(action,true);
                Time.timeScale=1;
            }
            foreach(var a in Demo.body.GetComponentsInChildren<ArticulationBody>())
            {
                var observer=a.gameObject.AddComponent<DiagnosticContactObserver>();observer.Owner=a;
                if(caseIndex==0)rig.WriteLine(JsonUtility.ToJson(new RigRow(a)));
            }
            Physics.SyncTransforms();
            resetLog.WriteLine(JsonUtility.ToJson(new ResetRow{trial=Trial,position=position,rotation=rotation,linearVelocity=root.linearVelocity,angularVelocity=root.angularVelocity,jointPositions=GetPositions(root),jointVelocities=GetVelocities(root),phase=Demo.controller.Phase,attached=Demo.body.Legs.Count(l=>l.FootAdhesion.Attached)}));
            foreach (var leg in Demo.body.Legs)
                leg.FootAdhesion.DiagnosticDrivenByController=IsLive||WindowsReplayDemo.Flag("-diagnosticOrderedAdhesion");
            Demo.controller.DiagnosticTargetObserved += ObserveTarget;
            ticks=0;started=Time.fixedTime;Elapsed=0;Recording=true;StartCoroutine(RecordTicks());
        }
        static float[] GetPositions(ArticulationBody root){var l=new List<float>();root.GetJointPositions(l);return l.ToArray();}
        static float[] GetVelocities(ArticulationBody root){var l=new List<float>();root.GetJointVelocities(l);return l.ToArray();}
        IEnumerator RecordTicks()
        {
            while(ticks<(IsGoal?3000:400)&&!goalPassed)
            {
                yield return new WaitForFixedUpdate();ticks++;Elapsed=ticks*.02f;
                if(IsLive){
                    Demo.client.TryGetLatestFrame(out var f,out double age);
                    liveLog.WriteLine(string.Join(",",new[]{F(Elapsed),(f?.sequence??-1).ToString(),f?.requestedAction??"NONE",F(f?.motor?.forward??0),F(f?.motor?.turn??0),f?.metadata?.backendId??"NONE",(f?.metadata?.ready??false).ToString(),age.ToString("R",CultureInfo.InvariantCulture),Demo.client.LastError,DateTime.UtcNow.ToString("o")}));
                    if(!string.IsNullOrEmpty(Demo.client.LastError)){Recording=false;Application.Quit(2);yield break;}
                }
                var b=Demo.body;var p=b.Position;var v=b.LinearVelocity;var com=b.Thorax.worldCenterOfMass;
                float ly=0,damping=0;foreach(var a in b.GetComponentsInChildren<ArticulationBody>()){var q=a.transform.rotation*a.inertiaTensorRotation;var spin=q*Vector3.Scale(a.inertiaTensor,Quaternion.Inverse(q)*a.angularVelocity);var orbital=Vector3.Cross(a.worldCenterOfMass,a.mass*a.linearVelocity);ly+=spin.y+orbital.y;damping-=(spin.y*a.angularDamping+orbital.y*a.linearDamping)*.02f;}
                bodyLog.WriteLine(string.Join(",",new[]{Trial,F(Elapsed),F(p.x),F(p.y),F(p.z),F(b.Thorax.transform.eulerAngles.y),F(v.x),F(v.y),F(v.z),F(b.AngularVelocity.y*Mathf.Rad2Deg),F(com.x),F(com.y),F(com.z),F(Demo.controller.Phase),p.y< -3?"1":"0",F(ly),F(damping)}));
                foreach(var leg in b.Legs)RecordLeg(leg);
            }
            Recording=false;
            if(IsGoal)File.WriteAllText(Path.Combine(output,"goal-result.json"),"{\"passed\":"+(goalPassed?"true":"false")+",\"elapsed\":"+F(Elapsed)+",\"distance\":"+F(Vector3.ProjectOnPlane(goalPosition-Demo.body.Position,Vector3.up).magnitude)+"}");
            Debug.Log("FIXED_DIAGNOSTIC_DONE "+Trial);
            if(++caseIndex<cases.Count)SceneManager.LoadScene(SceneManager.GetActiveScene().path);else {
                if(IsLive){Demo.client.SetAction("STOP",true);yield return new WaitForSecondsRealtime(4);Demo.client.Disconnect();}
                Close();Application.Quit();}
        }
        [Serializable]class GoalConfig{public string direction;public Vector3 target,start;}
        void UpdateGoal()
        {
            var delta=Vector3.ProjectOnPlane(goalPosition-Demo.body.Position,Vector3.up);
            float angle=Vector3.SignedAngle(Vector3.ProjectOnPlane(Demo.body.Thorax.transform.forward,Vector3.up),delta,Vector3.up);
            float speed=Vector3.ProjectOnPlane(Demo.body.LinearVelocity,Vector3.up).magnitude;
            Demo.client.TryGetLatestFrame(out var frame,out double age);
            bool stopped=frame!=null&&frame.requestedAction=="STOP"&&age<=.75&&Mathf.Abs(frame.motor.forward)<.01f&&Mathf.Abs(frame.motor.turn)<.01f;
            float now=Time.realtimeSinceStartup;var pos=Demo.body.Position;
            goalPoses.Enqueue(new Vector4(pos.x,pos.y,pos.z,now));
            while(goalPoses.Count>0&&now-goalPoses.Peek().w>1f)goalPoses.Dequeue();
            bool poseStill=goalPoses.Count>0&&now-goalPoses.Peek().w>=.9f;
            if(poseStill){var first=goalPoses.Peek();foreach(var q in goalPoses)if(Vector3.Distance(new Vector3(q.x,q.y,q.z),new Vector3(first.x,first.y,first.z))>.05f)poseStill=false;}
            goalStable=delta.magnitude<=.4f&&poseStill&&stopped?goalStable+Time.unscaledDeltaTime:0;
            if(goalStable>=1)goalPassed=true;
            if(Time.realtimeSinceStartup>=nextGoalCommand){
                float elapsedYaw=now-observedYawTime;
                float yaw=Demo.body.Thorax.transform.eulerAngles.y;
                if(observedYawTime>0&&elapsedYaw>0)filteredYawRate=Mathf.Lerp(filteredYawRate,Mathf.DeltaAngle(observedYaw,yaw)/elapsedYaw,.3f);
                observedYaw=yaw;observedYawTime=now;
                Vector3 observedVelocity=Vector3.zero;
                if(goalPoses.Count>0){var first=goalPoses.Peek();float dt=now-first.w;if(dt>.1f)observedVelocity=(pos-new Vector3(first.x,first.y,first.z))/dt;}
                float closingSpeed=Mathf.Max(0,Vector3.Dot(observedVelocity,delta.normalized));
                float stopDistance=closingSpeed*predictedStopSeconds;
                string wanted=delta.magnitude<=.4f?"STOP":Mathf.Abs(angle)>20?(angle>0?"TURN_R":"TURN_L"):"FORWARD";
                if(PredictiveGoal){
                    if(goalAction=="STOP"){
                        // Finish the STOP response before issuing an opposite stimulus.
                        if(!stopped||!poseStill)wanted="STOP";
                        else if(goalCommandTime>0)predictedStopSeconds=Mathf.Clamp(Mathf.Lerp(predictedStopSeconds,now-goalCommandTime,.5f),.5f,6);
                    }else if(age>.75)wanted="STOP";
                    else if(delta.magnitude<=.4f+stopDistance)wanted="STOP";
                    else if(frame==null||frame.requestedAction!=goalAction)wanted=goalAction;
                    else if(goalAction.StartsWith("TURN_")){
                        float overshoot=Mathf.Clamp(Mathf.Max(0,Mathf.Sign(angle)*filteredYawRate)*predictedStopSeconds,0,80);
                        if(Mathf.Abs(angle)<=15+overshoot)wanted="STOP";
                        else wanted=goalAction;
                    }else if(Mathf.Abs(angle)>25)wanted="STOP";
                }
                if(wanted!=goalAction){goalAction=wanted;goalCommandTime=now;Demo.client.SetAction(wanted,true);}
                nextGoalCommand=now+(PredictiveGoal?.2f:2f);
                var p=Demo.body.Position;
                goalLog.WriteLine(string.Join(",",new[]{F(Elapsed),F(delta.magnitude),F(angle),goalAction,F(p.x),F(p.z),F(goalPosition.x),F(goalPosition.z),F(speed),F(goalStable),F(predictedStopSeconds),F(stopDistance),F(filteredYawRate)}));
            }
        }
        void ObserveTarget(FlyLeg leg, FlyLeg.LegDriveTarget target)
        {
            if (Recording) {
                RecordSupport(leg,target.stance,target.angles,"BEFORE_APPLY");
                if(IsLive && leg.LegId=="LF") {
                    var frame=Demo.live.LatestFrame;var motor=Demo.controller.CurrentMotor;
                    motorUse.WriteLine(string.Join(",",new[]{F((ticks+1)*.02f),DateTime.UtcNow.ToString("o"),(frame?.sequence??-1).ToString(),frame?.requestedAction??"NONE",F(frame?.motor?.forward??0),F(frame?.motor?.turn??0),Demo.live.LatestFrameAgeSeconds.ToString("R",CultureInfo.InvariantCulture),Demo.live.HasFreshFrame?"1":"0",F(motor.forward),F(motor.turn),F(Demo.controller.Phase)}));
                }
            }
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
            legs.WriteLine(string.Join(",",new[]{Trial,F(Elapsed),l.LegId,F(ObservedFrame.motor.forward),F(ObservedFrame.motor.turn),F(m.forward),F(m.turn),F(ph),F(offset),Mathf.Sin(ph)<=0?"1":"0",F(.5f/config.gaitFrequencyHz),F(scale),F(unclamped),Mathf.Abs(scale-unclamped)>.0001f?"1":"0",F(drive),F(config.coxaStrideAmplitudeDegrees*drive*scale),F(config.coxaStrideAmplitudeDegrees*drive*scale),F(config.femurLiftAmplitudeDegrees*drive),F(config.tibiaLiftAmplitudeDegrees*drive),F(l.LastCorrectedCoxaTarget),F(l.Coxa.Target),F(Actual(l.Coxa)),F(l.Coxa.Articulation.jointVelocity[0]),F(l.Coxa.Articulation.jointForce[0]),F(l.LastCorrectedFemurTarget),F(l.Femur.Target),F(Actual(l.Femur)),F(l.LastCorrectedTibiaTarget),F(l.Tibia.Target),F(Actual(l.Tibia)),clamp?"1":"0",l.IsGrounded?"1":"0",a.Attached?"1":"0",F(a.NormalForceNewtons),F(a.ShearForceNewtons),a.ShearOverloadDetachCount.ToString(),a.ContactLostDetachCount.ToString(),a.SwingDetachCount.ToString(),F(force.x),F(force.y),F(force.z),F(yawImpulse)}));
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
        void Close(){SceneManager.sceneLoaded-=Loaded;legs?.Dispose();contacts?.Dispose();bodyLog?.Dispose();resetLog?.Dispose();rig?.Dispose();pairs?.Dispose();support?.Dispose();liveLog?.Dispose();motorUse?.Dispose();goalLog?.Dispose();
            if(IsLive&&Demo!=null){Demo.client.ReceivedLine-=Received;Demo.client.SentLine-=Sent;Demo.client.Disconnect();}
            lock(wireLock){wire?.Dispose();wire=null;}}
        void OnDestroy(){if(Current==this)Close();}
    }
    public sealed class DiagnosticContactObserver : MonoBehaviour
    {
        public ArticulationBody Owner;
        void OnCollisionEnter(Collision c)=>FixedPhysicsDiagnostic.Current?.Contact(Owner,c);
        void OnCollisionStay(Collision c)=>FixedPhysicsDiagnostic.Current?.Contact(Owner,c);
    }
}
