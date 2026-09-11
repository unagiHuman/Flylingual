using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using FlyLocomotionPoC;
using FlyBrainPoC;
using FlyVisualDemo;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;

public static class WindowsDemoBuilder
{
    const string Scene = "Assets/VisualDemo/WindowsReplayDemo.unity";
    const string BaseScene = "Assets/Scenes/FlyLocomotionSandbox.unity";
    static readonly string Repo = Path.GetFullPath(Path.Combine(Application.dataPath,"../.."));
    public static void BuildBaseline()
    {
        Build(BaseScene, Path.Combine(Repo,"artifacts/windows/baseline/FlyBaseline.exe"));
    }
    public static void CreateAndBuild()
    {
        Create(); Build(Scene,Path.Combine(Repo,"artifacts/windows/demo/FlyAscent.exe"));
    }
    public static void BuildDemo() => Build(Scene,Path.Combine(Repo,"artifacts/windows/demo/FlyAscent.exe"));
    public static void BuildMaleCnsIntegration()
    {
        foreach (string file in new[]{"shiu_game_brain_controller_frames_wire_v1.jsonl","malecns_game_brain_controller_frames_wire_v1.jsonl"})
        {
            var lines=File.ReadAllLines(Path.Combine(Repo,"Contracts/fixtures",file)).Where(s=>!string.IsNullOrWhiteSpace(s)).ToArray();
            var frames=lines.Select(s=>JsonUtility.FromJson<BrainFrame>(s)).ToArray();
            if(frames.Any(f=>f==null||f.motor==null||f.performance==null)) throw new Exception("Invalid BrainFrame: "+file);
            if(frames.Select(f=>f.requestedAction).Distinct().Count()!=6) throw new Exception("Missing actions");
            if(file.StartsWith("malecns") && (frames.Length!=76||frames.Any(f=>f.metadata?.backendId!="MALECNS_EXPERIMENTAL"||f.metadata.ready||f.raw?.populationDeltaMv==null))) throw new Exception("MaleCNS metadata/readout mismatch");
            Directory.CreateDirectory(Path.Combine(Repo,"artifacts/windows/m1"));
            File.WriteAllLines(Path.Combine(Repo,"artifacts/windows/m1",file+".parsed.jsonl"),frames.Select(f=>JsonUtility.ToJson(f)));
            Debug.Log("INTEGRATION_PARSER_PASS "+file+" frames="+frames.Length);
        }
        Build(Scene,Path.Combine(Repo,"artifacts/windows/m1/player/FlyAscent.exe"));
    }
    public static void ApplySignedSteeringAndBuild()
    {
        var preset=AssetDatabase.LoadAssetAtPath<FlyGameplayPreset>("Assets/Config/FlyGameplayPreset.asset");
        preset.steeringGain=1.5f;preset.minimumSideScale=-.5f;
        EditorUtility.SetDirty(preset);AssetDatabase.SaveAssets();CreateAndBuild();
    }
    static void Build(string scene,string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions { scenes=new[]{scene},locationPathName=path,target=BuildTarget.StandaloneWindows64,options=BuildOptions.Development });
        if(report.summary.result!=BuildResult.Succeeded) throw new Exception("Windows build: "+report.summary.result);
        Debug.Log("WINDOWS_BUILD_PASS "+path);
    }
    [MenuItem("FlyBrain/Windows/Create Replay Demo")]
    public static void Create()
    {
        ValidateGameRules();
        Directory.CreateDirectory("Assets/VisualDemo"); Directory.CreateDirectory("Assets/StreamingAssets");
        File.Copy(Path.Combine(Repo,"Contracts/fixtures/shiu_game_brain_controller_frames_wire_v1.jsonl"),"Assets/StreamingAssets/shiu_game_brain_controller_frames_wire_v1.jsonl",true);
        AssetDatabase.Refresh();
        var scene=EditorSceneManager.OpenScene(BaseScene);
        var body=UnityEngine.Object.FindFirstObjectByType<FlyBody>();
        if(body==null || body.Legs.Count!=6) throw new Exception("Expected six-leg baseline");
        string before=PhysicsSnapshot(body);
        foreach(var d in UnityEngine.Object.FindObjectsByType<FlyLocomotionDiagnostics>(FindObjectsSortMode.None)) d.enabled=false;
        foreach(var d in UnityEngine.Object.FindObjectsByType<FlyActionCharacterization>(FindObjectsSortMode.None)) d.enabled=false;
        foreach(var m in UnityEngine.Object.FindObjectsByType<MockMotorSource>(FindObjectsSortMode.None)) m.enabled=false;
        var client=UnityEngine.Object.FindFirstObjectByType<BrainTcpClient>(FindObjectsInactive.Include);
        var live=UnityEngine.Object.FindFirstObjectByType<BrainMotorSource>(FindObjectsInactive.Include);
        client.enabled=false;
        var clientSO=new SerializedObject(client); clientSO.FindProperty("connectOnStart").boolValue=false; clientSO.ApplyModifiedPropertiesWithoutUndo();
        var root=new GameObject("WindowsReplayDemo");
        var demo=root.AddComponent<WindowsReplayDemo>();
        Directory.CreateDirectory("Assets/Config");
        var preset=AssetDatabase.LoadAssetAtPath<FlyGameplayPreset>("Assets/Config/FlyGameplayPreset.asset");
        if(preset==null){preset=ScriptableObject.CreateInstance<FlyGameplayPreset>();AssetDatabase.CreateAsset(preset,"Assets/Config/FlyGameplayPreset.asset");}
        demo.gameplayPreset=preset;
        root.AddComponent<AscentGameSession>().demo=demo;
        root.AddComponent<SteeringTrial>();
        root.AddComponent<CourseTrial>();
        demo.body=body; demo.controller=body.GetComponent<FlyLocomotionController>(); demo.replay=root.AddComponent<ReplayMotorSource>(); demo.live=live; demo.client=client;
        demo.controller.SetMotorSource(demo.replay);
        foreach(var r in body.GetComponentsInChildren<Renderer>()) r.enabled=false;
        var visual=new GameObject("VisualRig"); demo.visualRig=visual.transform;
        var map=visual.AddComponent<VisualRigMapper>(); var bindings=new List<VisualRigMapper.Binding>();
        var model=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/FlyVisual/FlyVisual.fbx");
        if(model==null) throw new Exception("FlyVisual.fbx is required");
        var torso=(GameObject)PrefabUtility.InstantiatePrefab(model); torso.name="Thorax_Visual"; torso.transform.SetParent(visual.transform,false);
        torso.AddComponent<FlyWingBuzz>();
        torso.transform.SetPositionAndRotation(body.Thorax.transform.position,body.Thorax.transform.rotation);
        bindings.Add(new VisualRigMapper.Binding { joint="Thorax",physics=body.Thorax.transform,visual=torso.transform });
        foreach(var r in torso.GetComponentsInChildren<Renderer>())
        {
            var mats=r.sharedMaterials;
            for(int i=0;i<mats.Length;i++) mats[i]=FlyMaterial(mats[i]==null?"ChitinGold":mats[i].name);
            r.sharedMaterials=mats;
        }
        foreach(var leg in body.Legs)
        {
            // The frozen rig's hips sit outside the anatomical thorax silhouette.
            // A visual-only proximal bridge closes that gap without moving a joint.
            Vector3 hipStart=body.Position+body.Thorax.transform.right*(leg.LeftSide?-.4f:.4f)+body.Thorax.transform.up*-.06f+
                body.Thorax.transform.forward*Mathf.Clamp(Vector3.Dot(leg.Coxa.transform.position-body.Position,body.Thorax.transform.forward),-.6f,.6f);
            Vector3 hipAxis=leg.Coxa.transform.position-hipStart;
            var hip=new GameObject(leg.LegId+"_ThoraxBridge");hip.transform.SetParent(visual.transform,false);
            hip.transform.SetPositionAndRotation(hipStart,Quaternion.LookRotation(hipAxis,body.Thorax.transform.up));hip.transform.localScale=new Vector3(1,1,hipAxis.magnitude);
            Segment(hip.transform,Vector3.zero,Vector3.forward,.08f,FlyMaterial("ChitinGold"));
            bindings.Add(new VisualRigMapper.Binding {joint=leg.LegId+"_ThoraxBridge",physics=body.Thorax.transform,physicsTip=leg.Coxa.transform,visual=hip.transform,positionOffset=body.Thorax.transform.InverseTransformPoint(hipStart)});
            var joints=new[]{leg.Coxa,leg.Femur,leg.Tibia};
            for(int i=0;i<3;i++)
            {
                Transform p=joints[i].transform;
                Transform end=i<2?joints[i+1].transform:leg.FootContact.transform;
                var bone=new GameObject(p.name+"_VisualBone"); bone.transform.SetParent(visual.transform,false);
                Vector3 axis=end.position-p.position;
                bone.transform.SetPositionAndRotation(p.position,Quaternion.LookRotation(axis,p.rotation*Vector3.up)); bone.transform.localScale=new Vector3(1,1,axis.magnitude);
                Vector3 tip=Vector3.forward;
                Segment(bone.transform,Vector3.zero,tip,i==0?.075f:i==1?.06f:.037f,FlyMaterial("ChitinGold"));
                for(int h=0;h<4;h++)
                { Vector3 v=tip*((h+1)/5f); Segment(bone.transform,v,v+new Vector3((h%2==0?1:-1)*.075f,0,-.065f),.007f,FlyMaterial("Bristle")); }
                if(i==2) { Segment(bone.transform,tip,tip+new Vector3(.05f,0,.045f),.018f,FlyMaterial("AbdomenDark")); Segment(bone.transform,tip,tip+new Vector3(-.05f,0,.045f),.018f,FlyMaterial("AbdomenDark")); }
                bindings.Add(new VisualRigMapper.Binding {joint=p.name,physics=p,physicsTip=end,visual=bone.transform});
            }
        }
        map.bindings=bindings.ToArray(); map.Calibrate();
        if(map.bindings.Length!=25) throw new Exception("Expected thorax + 18 joint mappings + 6 visual hip bridges");
        if(visual.GetComponentsInChildren<Collider>(true).Length+visual.GetComponentsInChildren<Rigidbody>(true).Length+visual.GetComponentsInChildren<ArticulationBody>(true).Length!=0) throw new Exception("Unexpected physics in VisualRig");
        demo.view=Camera.main; demo.view.fieldOfView=43; demo.view.backgroundColor=new Color(.035f,.07f,.08f); demo.view.clearFlags=CameraClearFlags.SolidColor;
        demo.view.rect=new Rect(.27f,0,.73f,1);
        var ground=GameObject.Find("Ground");
        if(ground!=null)
        {
            ground.GetComponent<Renderer>().sharedMaterial=Material("Desk",new Color(.12f,.2f,.21f),0,.3f);
            // Finite tabletop in the demo scene; the source sandbox is never saved.
            ground.transform.position=new Vector3(0,-.1f,3);
            ground.transform.localScale=new Vector3(12,.2f,12);
        }
        Stage();
        foreach(var light in UnityEngine.Object.FindObjectsByType<Light>(FindObjectsSortMode.None)) {light.color=new Color(1,.85f,.64f);light.intensity=2.5f;light.shadows=LightShadows.Soft;}
        var fill=new GameObject("Cool rim").AddComponent<Light>(); fill.type=LightType.Directional; fill.color=new Color(.4f,.75f,1);fill.intensity=1;fill.transform.rotation=Quaternion.Euler(40,140,0);
        RenderSettings.ambientLight=new Color(.25f,.3f,.34f);
        string after=PhysicsSnapshot(body);
        if(before!=after) throw new Exception("Physics changed while adding visuals");
        Directory.CreateDirectory(Path.Combine(Repo,"artifacts/windows"));
        File.WriteAllText(Path.Combine(Repo,"artifacts/windows/physics_invariance.txt"),before);
        EditorSceneManager.SaveScene(scene,Scene); AssetDatabase.SaveAssets();
        Debug.Log("WINDOWS_DEMO_CREATED mappings=18+thorax+6visualBridges visualPhysics=0 physicsUnchanged=true");
    }
    static string PhysicsSnapshot(FlyBody b)
    {
        return string.Join("\n",b.GetComponentsInChildren<ArticulationBody>().Select(x=>x.name+":"+EditorJsonUtility.ToJson(x)))+"\n"+
            string.Join("\n",b.GetComponentsInChildren<Collider>().Select(x=>x.name+":"+EditorJsonUtility.ToJson(x)))+"\n"+EditorJsonUtility.ToJson(b.Config);
    }
    static void ValidateGameRules()
    {
        Vector3 goal=new Vector3(0,.5f,7);
        if(AscentGameSession.Evaluate(new Vector3(0,.5f,0),goal,1.5f)!=AscentGameSession.Phase.Running ||
           AscentGameSession.Evaluate(goal,goal,1.5f)!=AscentGameSession.Phase.Goal ||
           AscentGameSession.Evaluate(new Vector3(0,-4,7),goal,1.5f)!=AscentGameSession.Phase.Fallen ||
           AscentGameSession.Evaluate(goal+Vector3.up*3,goal,1.5f)!=AscentGameSession.Phase.Running ||
           AscentGameSession.Evaluate(new Vector3(0,-.05f,7),goal,1.5f)!=AscentGameSession.Phase.Running ||
           AscentGameSession.Evaluate(goal+Vector3.right*2,goal,1.5f)!=AscentGameSession.Phase.Running)
            throw new Exception("Game rule boundary validation failed");
        Debug.Log("GAME_RULES_PASS spawn,goal,fall,vertical-separation,below-platform,outside-radius; synthetic rule checks only");
        var config=ScriptableObject.CreateInstance<FlyLocomotionConfig>();
        if(!Mathf.Approximately(config.SideScale(true,-1),.5f) || !Mathf.Approximately(config.SideScale(false,-1),1.5f))throw new Exception("Legacy steering changed");
        config.steeringGain=1.5f;config.minimumSideScale=-.5f;
        if(!Mathf.Approximately(config.SideScale(true,-1),-.5f) || !Mathf.Approximately(config.SideScale(false,1),-.5f) || config.SideScale(true,0)!=1 || config.SideScale(false,0)!=1)throw new Exception("Signed steering boundary failed");
        UnityEngine.Object.DestroyImmediate(config);Debug.Log("STEERING_MAPPING_PASS legacy-default,signed-left,signed-right,zero-turn");
    }
    static Material FlyMaterial(string name)
    {
        Color c;float metal=.1f,smooth=.45f;
        if(name.Contains("Eye")) {c=new Color(.42f,.018f,.025f);smooth=.55f;}
        else if(name.Contains("WingMembrane")) c=new Color(.73f,.86f,.87f,.29f);
        else if(name.Contains("AbdomenDark")||name.Contains("Bristle")) c=new Color(.045f,.03f,.018f);
        else if(name.Contains("WingVein")) c=new Color(.3f,.25f,.12f);
        else c=new Color(.48f,.25f,.07f);
        return Material(name,c,metal,smooth);
    }
    static Material Material(string name,Color color,float metallic=0,float smooth=.4f)
    {
        string path="Assets/VisualDemo/"+name+".mat";
        var m=AssetDatabase.LoadAssetAtPath<Material>(path);
        if(m!=null)return m;
        m=new Material(Shader.Find("Universal Render Pipeline/Lit"));m.name=name;m.SetColor("_BaseColor",color);m.SetFloat("_Metallic",metallic);m.SetFloat("_Smoothness",smooth);
        if(color.a<1) {m.SetFloat("_Surface",1);m.SetFloat("_Blend",0);m.SetInt("_SrcBlend",(int)UnityEngine.Rendering.BlendMode.SrcAlpha);m.SetInt("_DstBlend",(int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);m.SetInt("_ZWrite",0);m.SetFloat("_Cull",0);m.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");m.renderQueue=3000;}
        AssetDatabase.CreateAsset(m,path);return m;
    }
    static void Segment(Transform parent,Vector3 a,Vector3 b,float radius,Material material)
    {
        var o=GameObject.CreatePrimitive(PrimitiveType.Cylinder);UnityEngine.Object.DestroyImmediate(o.GetComponent<Collider>());
        o.name="Visual segment";o.transform.SetParent(parent,false);o.transform.localPosition=(a+b)*.5f;o.transform.localRotation=Quaternion.FromToRotation(Vector3.up,b-a);o.transform.localScale=new Vector3(radius*2,(b-a).magnitude*.5f,radius*2);o.GetComponent<Renderer>().sharedMaterial=material;
    }
    static GameObject Prop(string name,PrimitiveType kind,Vector3 pos,Vector3 size,Color color)
    {
        var p=GameObject.CreatePrimitive(kind);p.name=name;p.transform.position=pos;p.transform.localScale=size;p.GetComponent<Renderer>().sharedMaterial=Material(name,color);p.AddComponent<FlyGroundMarker>();return p;
    }
    static void Stage()
    {
        // Open first route to sugar; optional elevated props establish the later ascent.
        Prop("Book - field notes",PrimitiveType.Cube,new Vector3(6,.12f,3),new Vector3(4,.24f,3),new Color(.66f,.26f,.12f));
        Prop("Book pages",PrimitiveType.Cube,new Vector3(6,.3f,3),new Vector3(3.9f,.15f,2.9f),new Color(.82f,.75f,.57f));
        Prop("Book - second volume",PrimitiveType.Cube,new Vector3(6,.65f,4),new Vector3(4,.55f,3),new Color(.13f,.32f,.38f));
        Prop("Coffee cup",PrimitiveType.Cylinder,new Vector3(5,1.1f,9),new Vector3(2.5f,1.1f,2.5f),new Color(.82f,.72f,.5f));
        Prop("Coffee",PrimitiveType.Cylinder,new Vector3(5,2.21f,9),new Vector3(2.2f,.015f,2.2f),new Color(.04f,.022f,.015f));
        Prop("Can",PrimitiveType.Cylinder,new Vector3(-5,1.5f,10),new Vector3(2.2f,1.5f,2.2f),new Color(.18f,.4f,.4f));
        for(int r=0;r<3;r++)for(int c=0;c<6;c++)Prop("Key "+r+"-"+c,PrimitiveType.Cube,new Vector3(-8+c*.85f,.2f,8+r*.85f),new Vector3(.76f,.4f,.76f),new Color(.32f,.39f,.4f));
        Prop("Narrow ledge",PrimitiveType.Cube,new Vector3(-1,1.5f,12),new Vector3(1.2f,.2f,5),new Color(.65f,.38f,.14f));
        var ramp=Prop("First climb - notebook ramp",PrimitiveType.Cube,new Vector3(0,.025f,2.8f),new Vector3(12,.03f,2.2f),new Color(.45f,.28f,.17f));
        ramp.transform.rotation=Quaternion.Euler(-2,0,0);
        Prop("Notebook summit",PrimitiveType.Cube,new Vector3(0,.04f,4.5f),new Vector3(12,.08f,1.2f),new Color(.61f,.35f,.19f));
        for(int i=0;i<3;i++) Prop("Sugar crystal "+i,PrimitiveType.Cube,new Vector3((i-1)*.45f,.30f,5f),new Vector3(.3f,.44f,.3f),new Color(.96f,.92f,.77f));
        for(int i=0;i<32;i++)
        {
            float angle=i*Mathf.PI*2/32;
            var marker=Prop("Goal rim "+i,PrimitiveType.Cube,new Vector3(Mathf.Sin(angle)*.85f,.09f,4.5f+Mathf.Cos(angle)*.85f),new Vector3(.08f,.012f,.08f),new Color(.7f,.8f,.35f));
            UnityEngine.Object.DestroyImmediate(marker.GetComponent<Collider>());
        }
        var label=new GameObject("Sugar goal label").AddComponent<TextMesh>();
        label.text="SUGAR / GOAL";label.fontSize=64;label.characterSize=.045f;label.anchor=TextAnchor.MiddleCenter;
        label.color=new Color(1,.9f,.6f);label.transform.position=new Vector3(0,.09f,5f);label.transform.rotation=Quaternion.Euler(90,180,0);
    }
}
