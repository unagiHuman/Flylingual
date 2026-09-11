using System;
using System.IO;
using System.Globalization;
using UnityEngine;
using FlyLocomotionPoC;

namespace FlyVisualDemo
{
    [DefaultExecutionOrder(1000)]
    public sealed class SteeringTrial : MonoBehaviour
    {
        WindowsReplayDemo demo;
        StreamWriter log;
        float began;
        bool active;
        string action;
        float simulated;
        void Start()
        {
            action=WindowsReplayDemo.Argument("-steeringTrial");
            if(string.IsNullOrEmpty(action)){enabled=false;return;}
            demo=GetComponent<WindowsReplayDemo>();
            demo.loop=true;demo.SelectReplay("STOP");began=Time.unscaledTime;
            log=new StreamWriter(Path.Combine(WindowsReplayDemo.Argument("-demoOutput"),"steering.csv"));
            log.AutoFlush=true;
            log.WriteLine("t,active,action,sequence,rawForward,rawTurn,cpgForward,cpgTurn,leftScale,rightScale,phase,x,y,z,yaw,yawRate,leg,coxa,femur,tibia,attached,normalForce,shearForce,grip");
        }
        void FixedUpdate()
        {
            simulated+=Time.fixedDeltaTime;
            float t=simulated;
            if(!active && t>=2)
            {
                var config=Instantiate(demo.body.Config);
                if(float.TryParse(WindowsReplayDemo.Argument("-steeringGain"),NumberStyles.Float,CultureInfo.InvariantCulture,out float gain))config.steeringGain=gain;
                if(WindowsReplayDemo.Flag("-signedSteering"))config.minimumSideScale=-.5f;
                if(WindowsReplayDemo.Flag("-trialAdhesion")) demo.controller.ConfigureFootAdhesion(true,.12f,.1f,.02f,1.25f);
                demo.controller.Configure(demo.body,demo.replay,config);
                demo.controller.SetPhaseForDiagnostics(0);
                demo.SelectReplay(action);active=true;
                Debug.Log("STEERING_TRIAL_BEGIN action="+action+" gain="+config.steeringGain+" position="+demo.body.Position);
            }
            var f=demo.replay.LatestFrame;
            var c=demo.controller;var b=demo.body;
            foreach(var leg in b.Legs)
            {
                var a=leg.FootAdhesion;
                log.WriteLine(string.Join(",", new string[]{F(t),active?"1":"0",action,f.sequence.ToString(),F(f.motor.forward),F(f.motor.turn),F(c.CurrentMotor.forward),F(c.CurrentMotor.turn),F(c.LeftGaitScale),F(c.RightGaitScale),F(c.Phase),F(b.Position.x),F(b.Position.y),F(b.Position.z),F(b.Thorax.transform.eulerAngles.y),F(b.AngularVelocity.y*Mathf.Rad2Deg),leg.LegId,F(leg.Coxa.Target),F(leg.Femur.Target),F(leg.Tibia.Target),a!=null&&a.Attached?"1":"0",F(a==null?0:a.NormalForceNewtons),F(a==null?0:a.ShearForceNewtons),F(a==null?0:a.GripUtilization)}));
            }
        }
        static string F(float value)=>value.ToString("R",CultureInfo.InvariantCulture);
        void OnDestroy(){log?.Dispose();}
    }
}
