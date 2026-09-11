using System;
using System.IO;
using System.Globalization;
using FlyBrainPoC;
using UnityEngine;

namespace FlyVisualDemo
{
    // Observation and stimulus only. Never modifies motor output, pose or physical parameters.
    public sealed class LiveIntegrationTrial : MonoBehaviour
    {
        WindowsReplayDemo demo;
        StreamWriter wire, motion, events;
        readonly object sync=new object();
        string output;
        float entered, nextSample, nextImage, stable;
        int stage, imageIndex;
        bool sentStop, ended;
        Vector3 forwardOrigin, forwardDirection;
        float forwardDistance;
        readonly System.Collections.Generic.Queue<Vector4> poses=new System.Collections.Generic.Queue<Vector4>();
        readonly string[] movingActions={"FORWARD","TURN_R","TURN_L","FORWARD_R","FORWARD_L"};
        int actionIndex;
        void Awake()
        {
            demo=GetComponent<WindowsReplayDemo>(); output=WindowsReplayDemo.Argument("-demoOutput");
            wire=new StreamWriter(Path.Combine(output,"live-wire.jsonl")){AutoFlush=true};
            events=new StreamWriter(Path.Combine(output,"live-events.txt")){AutoFlush=true};
            motion=new StreamWriter(Path.Combine(output,"live-motion.csv")){AutoFlush=true};
            motion.WriteLine("time,stage,connection,sequence,action,forward,turn,age,cpgForward,cpgTurn,x,y,z,yaw,vx,vy,vz,yawRate,attached");
            demo.client.ReceivedLine+=Received; demo.client.SentLine+=Sent;
            entered=Time.realtimeSinceStartup; Log("START endpoint="+demo.client.Host+":"+demo.client.Port);
        }
        void Received(string line){lock(sync)wire?.WriteLine("{\"utc\":\""+DateTime.UtcNow.ToString("o")+"\",\"direction\":\"receive\",\"message\":"+line+"}");}
        void Sent(string line){lock(sync)wire?.WriteLine("{\"utc\":\""+DateTime.UtcNow.ToString("o")+"\",\"direction\":\"send\",\"message\":"+line+"}");}
        void Log(string text){events.WriteLine(DateTime.UtcNow.ToString("o")+" t="+F(Time.realtimeSinceStartup)+" "+text);Debug.Log("LIVE_TRIAL "+text);}
        void Stimulate(string action){Log("INPUT "+action);demo.client.SetAction(action,true);entered=Time.realtimeSinceStartup;stable=0;poses.Clear();}
        static string F(float x)=>x.ToString("R",CultureInfo.InvariantCulture);
        void Finish(string outcome)
        {
            if(ended)return; ended=true;Log(outcome);demo.client.Disconnect();
            ScreenCapture.CaptureScreenshot(Path.Combine(output,"live-result.png"));
            Invoke(nameof(Quit),1);
        }
        void Quit()=>Application.Quit();
        void Update()
        {
            if(ended)return;
            float now=Time.realtimeSinceStartup;
            var client=demo.client; var body=demo.body;
            client.TryGetLatestFrame(out BrainFrame frame,out double age);
            if(!string.IsNullOrEmpty(client.LastError)){Finish("FAIL client_error="+client.LastError);return;}
            if(now>=nextImage){nextImage=now+1;ScreenCapture.CaptureScreenshot(Path.Combine(output,"live-"+(imageIndex++).ToString("D3")+".png"));}
            if(now>=nextSample)
            {
                nextSample=now+.05f;int attached=0;foreach(var leg in body.Legs)if(leg.FootAdhesion!=null&&leg.FootAdhesion.Attached)attached++;
                var p=body.Position;var v=body.LinearVelocity;var motor=demo.controller.CurrentMotor;
                poses.Enqueue(new Vector4(p.x,p.y,p.z,body.Thorax.transform.eulerAngles.y));if(poses.Count>21)poses.Dequeue();
                motion.WriteLine(string.Join(",",new[]{F(now),stage.ToString(),client.ConnectionState,(frame?.sequence??-1).ToString(),frame?.requestedAction??"NONE",F(frame?.motor?.forward??0),F(frame?.motor?.turn??0),age.ToString("R",CultureInfo.InvariantCulture),F(motor.forward),F(motor.turn),F(p.x),F(p.y),F(p.z),F(body.Thorax.transform.eulerAngles.y),F(v.x),F(v.y),F(v.z),F(body.AngularVelocity.y*Mathf.Rad2Deg),attached.ToString()}));
            }
            if(stage==0)
            {
                if(client.ConnectionState=="CONNECTED"&&!sentStop){sentStop=true;Stimulate("STOP");}
                if(frame?.metadata?.backendId=="MALECNS_EXPERIMENTAL"&&frame.metadata.ready==false&&age<.75&&frame.requestedAction=="STOP"&&Mathf.Abs(frame.motor.forward)<.01f&&Mathf.Abs(frame.motor.turn)<.01f)
                    stable+=Time.unscaledDeltaTime;else stable=0;
                if(stable>=3)
                {
                    Log("INITIAL_STOP_PASS");stage=1;forwardOrigin=body.Position;forwardDirection=body.Thorax.transform.forward;Stimulate("FORWARD");
                }
                else if(now-entered>20)Finish("FAIL initial_stop_timeout");
            }
            else if(stage==1)
            {
                forwardDistance=Vector3.Dot(body.Position-forwardOrigin,forwardDirection);
                if(now-entered>=8)
                {
                    Log(movingActions[actionIndex]+"_OBSERVED distance="+F(forwardDistance));stage=2;Stimulate("STOP");
                }
            }
            else if(stage==2)
            {
                // Contact solver velocities can oscillate while the visible pose remains still.
                // Measure the observed pose envelope across 21 samples (~1 second), not solver velocity.
                bool poseStill=poses.Count==21;
                if(poseStill){var first=poses.Peek();foreach(var p in poses)if(Vector3.Distance(new Vector3(first.x,first.y,first.z),new Vector3(p.x,p.y,p.z))>.01f||Mathf.Abs(Mathf.DeltaAngle(first.w,p.w))>1)poseStill=false;}
                bool stopped=frame!=null&&frame.requestedAction=="STOP"&&age<.75&&Mathf.Abs(frame.motor.forward)<.01f&&Mathf.Abs(frame.motor.turn)<.01f&&poseStill;
                stable=stopped?stable+Time.unscaledDeltaTime:0;
                if(stable>=1)
                {
                    Log("PHYSICAL_STOP_CONFIRMED elapsed="+F(now-entered)+" criterion=pose_0.01_yaw_1deg");
                    if(actionIndex==0&&forwardDistance<=.1f){Finish("FAIL forward_distance");return;}
                    if(actionIndex==0)Log("BASIC_GATE_PASS");
                    if(WindowsReplayDemo.Flag("-liveSix")&&++actionIndex<movingActions.Length)
                    {stage=1;forwardOrigin=body.Position;forwardDirection=body.Thorax.transform.forward;Stimulate(movingActions[actionIndex]);}
                    else Finish("TRIAL_COMPLETE");
                }
                else if(now-entered>15)Finish("FAIL physical_stop_timeout");
            }
        }
        void OnDestroy()
        {
            if(demo!=null){demo.client.ReceivedLine-=Received;demo.client.SentLine-=Sent;demo.client.Disconnect();}
            lock(sync){wire?.Dispose();wire=null;}motion?.Dispose();events?.Dispose();
        }
    }
}
