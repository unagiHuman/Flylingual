using System;
using System.IO;
using System.Globalization;
using UnityEngine;

namespace FlyVisualDemo
{
    // Test driver only. Selects exactly the same recorded inputs as W/A/D.
    // Never changes motor data, body pose, physics forces, goal or stage geometry.
    [DefaultExecutionOrder(-100)]
    public sealed class CourseTrial : MonoBehaviour
    {
        AscentGameSession game;
        WindowsReplayDemo demo;
        string trial;
        StreamWriter log;
        float started,nextInput,nextSample,finished=-1;
        int attachmentSamples;
        static bool restarted;
        void Start()
        {
            trial=WindowsReplayDemo.Argument("-courseTrial");
            if(string.IsNullOrEmpty(trial)){enabled=false;return;}
            game=GetComponent<AscentGameSession>();demo=GetComponent<WindowsReplayDemo>();
            started=Time.realtimeSinceStartup;
            string outDir=WindowsReplayDemo.Argument("-demoOutput");
            log=new StreamWriter(Path.Combine(outDir,"course_"+DateTime.UtcNow.ToString("HHmmssfff")+".csv"));log.AutoFlush=true;
            log.WriteLine("t,state,x,y,z,yaw,headingError,input,attached,normalForce,rampContacts,summitContacts,headX,headY,headZ");
            Debug.Log("COURSE_TRIAL test-driver inputs only / "+trial+" restarted="+restarted);
        }
        string input="STOP";
        float error;
        void Update()
        {
            float t=Time.realtimeSinceStartup-started;
            if(t<1)return;
            if(game.Current==AscentGameSession.Phase.Ready)game.Begin();
            if(game.Current==AscentGameSession.Phase.Running && Time.unscaledTime>=nextInput)
            {
                nextInput=Time.unscaledTime+.3f;
                Vector3 target=trial=="fall"?new Vector3(8,0,0):game.goal;
                Vector3 delta=target-demo.body.Position;
                float desired=Mathf.Atan2(delta.x,delta.z)*Mathf.Rad2Deg;
                error=Mathf.DeltaAngle(demo.body.Thorax.transform.eulerAngles.y,desired);
                bool left=error < -5, right=error>12;
                game.SetRecordedInput(true,left,right);
                input=left?"FORWARD_L":right?"FORWARD_R":"FORWARD";
            }
            int attached=0,rampContacts=0,summitContacts=0;float force=0;
            foreach(var leg in demo.body.Legs)
            {
                if(leg.FootAdhesion!=null){if(leg.FootAdhesion.Attached)attached++;force+=leg.FootAdhesion.NormalForceNewtons;}
                if(leg.FootContact!=null && leg.FootContact.HasFreshSurfaceContact)
                {if(leg.FootContact.OtherColliderName.Contains("ramp"))rampContacts++;if(leg.FootContact.OtherColliderName.Contains("summit"))summitContacts++;}
            }
            if(attached>0)attachmentSamples++;
            if(Time.unscaledTime>=nextSample)
            {
                nextSample=Time.unscaledTime+.1f;var p=demo.body.Position;
                var head=game.GoalProbe;
                log.WriteLine(string.Join(",",new[]{F(t),game.Current.ToString(),F(p.x),F(p.y),F(p.z),F(demo.body.Thorax.transform.eulerAngles.y),F(error),input,attached.ToString(),F(force),rampContacts.ToString(),summitContacts.ToString(),F(head.x),F(head.y),F(head.z)}));
            }
            bool terminal=game.Current==AscentGameSession.Phase.Goal || game.Current==AscentGameSession.Phase.Fallen;
            if(terminal && finished<0)
            {
                finished=t;Debug.Log("COURSE_RESULT state="+game.Current+" attachedSamples="+attachmentSamples+" position="+demo.body.Position+" elapsed="+game.Elapsed);
                ScreenCapture.CaptureScreenshot(Path.Combine(WindowsReplayDemo.Argument("-demoOutput"),"course_"+game.Current+".png"));
            }
            if(finished>=0 && t>finished+1)
            {
                if(trial=="fall" && !restarted && game.Current==AscentGameSession.Phase.Fallen)
                {restarted=true;Debug.Log("COURSE_RESTART_REQUEST");demo.RestartDemo();}
                else Application.Quit();
            }
            if(restarted && t>2 && game.Current==AscentGameSession.Phase.Running)
            {Debug.Log("COURSE_RESTART_PASS position="+demo.body.Position);Application.Quit();}
        }
        static string F(float v)=>v.ToString("R",CultureInfo.InvariantCulture);
        void OnDestroy(){log?.Dispose();}
    }
}
