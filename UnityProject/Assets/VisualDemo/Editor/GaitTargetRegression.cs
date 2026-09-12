using System;
using System.IO;
using System.Globalization;
using UnityEngine;
using FlyLocomotionPoC;

public static class GaitTargetRegression
{
    public static void RunAndBuild()
    {
        string root=Path.GetFullPath(Path.Combine(Application.dataPath,"../.."));
        string fixture=Path.Combine(root,"artifacts/windows-malecns/coxa-check/baseline/legs.csv");
        if(!File.Exists(fixture))throw new FileNotFoundException("Recorded pre-refactor target fixture required",fixture);
        var go=new GameObject("Pure target regression");var leg=go.AddComponent<FlyLeg>();
        var c=ScriptableObject.CreateInstance<FlyLocomotionConfig>();
        c.coxaStrideAmplitudeDegrees=38;c.femurLiftAmplitudeDegrees=28;c.tibiaLiftAmplitudeDegrees=38;
        c.turnSign=-1;c.steeringGain=1.5f;c.minimumSideScale=-.5f;c.turnGaitContribution=.7f;
        int count=0;float maxError=0;
        try
        {
            using(var reader=new StreamReader(fixture))
            {
                var names=reader.ReadLine().Split(',');
                int Index(string name)=>Array.IndexOf(names,name);
                string line;
                while((line=reader.ReadLine())!=null)
                {
                    var row=line.Split(',');
                    float V(string key)=>float.Parse(row[Index(key)],CultureInfo.InvariantCulture);
                    string id=row[Index("leg")]; bool left=id[0]=='L';
                    var group=(id=="LF"||id=="LH"||id=="RM")?FlyLeg.TripodGroup.A:FlyLeg.TripodGroup.B;
                    leg.Configure(id,left,group,null,null,null,null);
                    var target=leg.CalculateNominalTargets(V("phase")-V("offset"),new FlyMotorCommand(V("cpgF"),V("cpgT")),c);
                    float error=Mathf.Max(Mathf.Abs(target.angles.x-V("coxaRaw")),Mathf.Abs(target.angles.y-V("femurRaw")),Mathf.Abs(target.angles.z-V("tibiaRaw")));
                    maxError=Mathf.Max(maxError,error);
                    if(error>.0001f || target.stance!=(row[Index("stance")]=="1"))throw new Exception("Target regression "+row[0]+" leg="+id+" error="+error);
                    count++;
                }
            }
            string result="{\"passed\":true,\"samples\":"+count+",\"maxAngleErrorDegrees\":"+maxError.ToString("R",CultureInfo.InvariantCulture)+"}";
            File.WriteAllText(Path.Combine(root,"artifacts/windows-malecns/gait-target-regression.json"),result);
            Debug.Log("GAIT_TARGET_REGRESSION_PASS "+result);
        }
        finally {UnityEngine.Object.DestroyImmediate(go);UnityEngine.Object.DestroyImmediate(c);}
        WindowsDemoBuilder.BuildMaleCnsIntegration();
    }
}
