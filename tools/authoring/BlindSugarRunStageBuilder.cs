using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>Authoring-only, environment-only Blind Sugar Run prototype.</summary>
public static class BlindSugarRunStageBuilder
{
    const string Root = "Assets/BlindSugarRunPrototype";
    const string ScenePath = Root + "/BlindSugarRunPrototype.unity";
    const string PrefabPath = Root + "/BlindSugarRunEnvironment.prefab";
    const string OverviewPath = "artifacts/blind-sugar-run-stage/overview.png";
    const string TopdownPath = "artifacts/blind-sugar-run-stage/topdown.png";
    static readonly Vector3 StageCenter = new Vector3(7f, 0f, 52f);
    static readonly List<Vector3> route = new List<Vector3> {
        new Vector3(0,0,0), new Vector3(0,0,21), new Vector3(0,0,29), new Vector3(9,0,53),
        new Vector3(9,0,64), new Vector3(-1,0,73), new Vector3(-1,0,96), new Vector3(5,0,104)
    };

    [Serializable] public sealed class ValidationReport
    {
        public string status, note, scene, prefab, sensors, physics, brain;
        public bool routeSupported, rulerSidesClear, dimensionsValid, noScripts, noBodies;
        public bool triggerCountValid, anchorsValid, prefabReloaded, sceneReloaded;
        public int goalTriggers, killTriggers, anchorCount;
        public int supportSamples;
        public bool wideRouteSupported, rootIdentity, visualCollidersAbsent;
        public string[] issues = new string[0];
    }

    [MenuItem("Flylingual/Blind Sugar Run/Create environment stage")]
    public static void Create()
    {
        RefuseExisting();
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        if (EditorSceneManager.GetActiveScene().isDirty) throw new InvalidOperationException("Save the current scene before creating the stage.");
        Directory.CreateDirectory(Path.Combine(Application.dataPath, "BlindSugarRunPrototype"));
        AssetDatabase.Refresh();
        Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        GameObject root = new GameObject("BlindSugarRunEnvironment");
        BuildEnvironment(root.transform);
        CreateDevelopmentCamera();
        CreateLighting();
        PrefabUtility.SaveAsPrefabAssetAndConnect(root, PrefabPath, InteractionMode.UserAction);
        if (!EditorSceneManager.SaveScene(scene, ScenePath)) throw new IOException("Could not save environment scene.");
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        ValidateAndCapture();
        Debug.Log("BLIND_SUGAR_ENVIRONMENT_CREATED " + ScenePath + " prefab=" + PrefabPath + " flyPlaced=false");
    }

    [MenuItem("Flylingual/Blind Sugar Run/Validate and capture")]
    public static void ValidateAndCapture()
    {
        if (!File.Exists(ScenePath))
            throw new InvalidOperationException("Create the environment stage first.");
        Scene scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        Physics.SyncTransforms();
        ValidationReport report = ValidateScene(scene);
        Capture("DevelopmentCamera", OverviewPath, false);
        Capture("TopdownCamera", TopdownPath, true);
        report.status = report.issues.Length == 0 ? "PASS_STATIC_GEOMETRY" : "FAIL_STATIC_GEOMETRY";
        report.note = "Static geometry validation only; Fly placement, traversal and Brain connection are unverified.";
        string reportDirectory = GetReportDirectory();
        Directory.CreateDirectory(reportDirectory);
        File.WriteAllText(Path.Combine(reportDirectory, "validation.json"), JsonUtility.ToJson(report, true));
        AssetDatabase.ImportAsset(ScenePath);
        Debug.Log("BLIND_SUGAR_ENVIRONMENT_VALIDATION " + report.status + " report=" + Path.Combine(reportDirectory, "validation.json"));
        if (report.issues.Length != 0) throw new InvalidOperationException("Static stage validation failed: " + string.Join(",", report.issues));
    }

    static void RefuseExisting()
    {
        if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(ScenePath) != null || AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(PrefabPath) != null)
            throw new InvalidOperationException("BlindSugarRunPrototype assets already exist; refusing overwrite.");
    }

    static void BuildEnvironment(Transform root)
    {
        Transform geometry = Child(root, "EnvironmentGeometry");
        Material desk = MaterialAsset("Desk", new Color(.20f,.24f,.23f));
        Material paper = MaterialAsset("Paper", new Color(.72f,.66f,.52f));
        Material ruler = MaterialAsset("Ruler", new Color(.72f,.51f,.20f));
        Material book = MaterialAsset("Book", new Color(.08f,.24f,.43f));
        Material ink = MaterialAsset("RulerInk", new Color(.10f,.13f,.14f));
        Material pencil = MaterialAsset("RedPencil", new Color(.55f,.085f,.06f));
        Material sugar = MaterialAsset("Sugar", new Color(.96f,.92f,.72f));
        Box(geometry, "StartArea", new Vector3(0,0,0), new Vector3(28,.8f,24), desk);
        Box(geometry, "PlanningArea", new Vector3(0,0,21), new Vector3(22,.8f,20), paper);
        Segment(geometry, "RulerBridge", new Vector3(0,0,29), new Vector3(9,0,53), 8, ruler);
        Box(geometry, "BookPlatform", new Vector3(9,0,64), new Vector3(24,.8f,24), book);
        Segment(geometry, "NarrowRoute", new Vector3(-1,0,73), new Vector3(-1,0,96), 6, ruler);
        Segment(geometry, "WideRouteA", new Vector3(19,0,72), new Vector3(34,0,78), 12, paper);
        Segment(geometry, "WideRouteB", new Vector3(34,0,78), new Vector3(34,0,97), 12, paper);
        Segment(geometry, "WideRouteC", new Vector3(34,0,97), new Vector3(14,0,103), 12, paper);
        Box(geometry, "GoalArea", new Vector3(5,0,104), new Vector3(26,.8f,20), desk);
        Box(geometry, "CatchRecovery", new Vector3(4.5f,-6,41), new Vector3(36,.8f,36), desk);
        Box(geometry, "WideConnectionPad1", new Vector3(34,0,78), new Vector3(14,.8f,14), paper);
        Box(geometry, "WideConnectionPad2", new Vector3(34,0,97), new Vector3(14,.8f,14), paper);
        Transform decorations = Child(root, "MinimalArt");
        ThinEdge(decorations, "RulerEdgeL", new Vector3(0,0.05f,29), new Vector3(9,0.05f,53), 3.9f, ruler);
        ThinEdge(decorations, "RulerEdgeR", new Vector3(0,0.05f,29), new Vector3(9,0.05f,53), -3.9f, ruler);
        Vector3 bridgeDirection = new Vector3(9, 0, 24).normalized;
        Vector3 bridgeRight = Vector3.Cross(Vector3.up, bridgeDirection);
        for (int i = 1; i < 24; i++)
        {
            float length = i % 5 == 0 ? 1.6f : .9f;
            Vector3 p = Vector3.Lerp(new Vector3(0, .015f, 29), new Vector3(9, .015f, 53), i / 24f);
            p += bridgeRight * (3.7f - length / 2);
            var tick = BoxVisual(decorations, "RulerTick_" + i, p, new Vector3(length, .02f, .08f), ink);
            tick.transform.rotation = Quaternion.LookRotation(bridgeDirection);
        }
        // Exposed pages below the unchanged blue supporting surface.
        BoxVisual(decorations, "BookPages", new Vector3(9, -1.1f, 64), new Vector3(23.5f, 1.2f, 23.5f), paper);
        BoxVisual(decorations, "BookBottomCover", new Vector3(9, -1.8f, 64), new Vector3(24, .2f, 24), book);
        BoxVisual(decorations, "OpenBookPages", new Vector3(4.5f, -6.9f, 41), new Vector3(35.5f, 1, 35.5f), paper);
        BoxVisual(decorations, "RedPencil", new Vector3(-11, .25f, -2), new Vector3(.7f, .5f, 13), pencil);
        CylinderVisual(decorations,"Plate",new Vector3(5,.08f,104),new Vector3(8,.08f,8),paper);
        for (int i=0;i<3;i++) BoxVisual(decorations,"Sugar"+i,new Vector3(3.4f+i*1.6f,.8f,106),new Vector3(1.3f,1.3f,1.3f),sugar);
        Transform volumes = Child(root, "Volumes");
        TriggerBox(volumes,"GoalVolume",new Vector3(5,2,102),new Vector3(6,4,6));
        TriggerBox(volumes,"KillVolume",new Vector3(0,-12,50),new Vector3(100,2,160));
        Transform anchors = Child(root, "Anchors");
        Anchor(anchors,"Start",new Vector3(0,1.45f,0),Quaternion.identity);
        Anchor(anchors,"RulerEntry",new Vector3(0,1.45f,29),Quaternion.LookRotation(new Vector3(9,0,24)));
        Anchor(anchors,"RulerExit",new Vector3(9,1.45f,53),Quaternion.identity);
        Anchor(anchors,"Branch",new Vector3(9,1.45f,70),Quaternion.identity);
        Anchor(anchors,"NarrowRoute",new Vector3(-1,1.45f,73),Quaternion.identity);
        Anchor(anchors,"WideRoute",new Vector3(19,1.45f,72),Quaternion.LookRotation(Vector3.right));
        Anchor(anchors,"Goal",new Vector3(5,1.45f,104),Quaternion.identity);
        Anchor(anchors,"CatchRecovery",new Vector3(4.5f,-4.55f,41),Quaternion.identity);
        Transform reveal = Child(root,"RevealCameraAnchors");
        Anchor(reveal,"RevealStart",new Vector3(11,7,94),Quaternion.LookRotation(new Vector3(5,1,104)-new Vector3(11,7,94)));
        Anchor(reveal,"RevealPullback",new Vector3(78,110,-24),Quaternion.LookRotation(StageCenter-new Vector3(78,110,-24)));
    }

    static Transform Child(Transform parent, string name)
    {
        var o = new GameObject(name);
        o.transform.SetParent(parent, false);
        return o.transform;
    }

    // Support positions describe the TOP surface, not the primitive centre.
    static GameObject Box(Transform parent, string name, Vector3 top, Vector3 size, Material material)
    {
        var o = BoxVisual(parent, name, top + Vector3.down * size.y * .5f, size, material);
        o.AddComponent<BoxCollider>().size = Vector3.one;
        return o;
    }

    static GameObject BoxVisual(Transform parent, string name, Vector3 position, Vector3 size, Material material)
    {
        var o = GameObject.CreatePrimitive(PrimitiveType.Cube);
        o.name = name;
        o.transform.SetParent(parent, false);
        o.transform.position = position;
        o.transform.localScale = size;
        o.GetComponent<Renderer>().sharedMaterial = material;
        UnityEngine.Object.DestroyImmediate(o.GetComponent<Collider>());
        return o;
    }

    static void Segment(Transform parent, string name, Vector3 a, Vector3 b, float width, Material material)
    {
        Vector3 direction = b - a;
        var o = Box(parent, name, (a + b) * .5f, new Vector3(width, .8f, direction.magnitude), material);
        o.transform.rotation = Quaternion.LookRotation(direction, Vector3.up);
    }

    static void ThinEdge(Transform parent, string name, Vector3 a, Vector3 b, float side, Material material)
    {
        Vector3 direction = (b - a).normalized;
        Vector3 offset = Vector3.Cross(Vector3.up, direction) * side;
        var o = BoxVisual(parent, name, (a + b) * .5f + offset, new Vector3(.12f, .04f, (b - a).magnitude), material);
        o.transform.rotation = Quaternion.LookRotation(direction);
    }

    static void CylinderVisual(Transform parent, string name, Vector3 position, Vector3 scale, Material material)
    {
        var o = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        o.name = name;
        o.transform.SetParent(parent, false);
        o.transform.position = position;
        o.transform.localScale = scale;
        o.GetComponent<Renderer>().sharedMaterial = material;
        UnityEngine.Object.DestroyImmediate(o.GetComponent<Collider>());
    }

    static void TriggerBox(Transform parent, string name, Vector3 position, Vector3 size)
    {
        Transform t = Child(parent, name);
        t.position = position;
        var collider = t.gameObject.AddComponent<BoxCollider>();
        collider.isTrigger = true;
        collider.size = size;
    }

    static void Anchor(Transform parent, string name, Vector3 position, Quaternion rotation)
    {
        Child(parent, name).SetPositionAndRotation(position, rotation);
    }

    static Material MaterialAsset(string name, Color color)
    {
        string path = Root + "/" + name + ".mat";
        if (AssetDatabase.LoadAssetAtPath<Material>(path) != null)
            throw new InvalidOperationException("Material exists: " + path);
        Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
        if (shader == null) throw new InvalidOperationException("No compatible surface shader.");
        var material = new Material(shader) { name = name, color = color };
        if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", .2f);
        AssetDatabase.CreateAsset(material, path);
        return material;
    }
    static void CreateDevelopmentCamera()
    {
        var o = new GameObject("DevelopmentCamera");
        o.tag = "MainCamera";
        var c = o.AddComponent<Camera>();
        c.transform.position = new Vector3(78, 110, -24);
        c.transform.LookAt(StageCenter);
        c.fieldOfView = 52;
        c.farClipPlane = 500;
        c.clearFlags = CameraClearFlags.SolidColor;
        c.backgroundColor = new Color(.08f, .09f, .1f);
        var t = new GameObject("TopdownCamera");
        var tc = t.AddComponent<Camera>();
        tc.enabled = false;
        tc.transform.position = new Vector3(7, 105, 52);
        tc.transform.rotation = Quaternion.Euler(90, 0, 0);
        tc.orthographic = true;
        tc.orthographicSize = 67;
        tc.farClipPlane = 500;
        tc.clearFlags = CameraClearFlags.SolidColor;
        tc.backgroundColor = c.backgroundColor;
    }

    static void CreateLighting()
    {
        var o = new GameObject("Directional Light");
        var l = o.AddComponent<Light>();
        l.type = LightType.Directional;
        l.intensity = 2;
        l.color = new Color(1, .94f, .82f);
        l.shadows = LightShadows.Soft;
        o.transform.rotation = Quaternion.Euler(50, -30, 0);
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(.4f, .44f, .5f);
        RenderSettings.skybox = null;
    }

    static ValidationReport ValidateScene(Scene s)
    {
        var r=new ValidationReport{scene=ScenePath,prefab=PrefabPath,sensors="NOT_CONNECTED",physics="ENVIRONMENT_COLLIDERS_ONLY",brain="NOT_CONNECTED"};var issues=new List<string>();
        Transform root=GameObject.Find("BlindSugarRunEnvironment")?.transform;if(root==null)issues.Add("root_missing");
        r.anchorCount=root==null?0:root.Find("Anchors").childCount;r.anchorsValid=r.anchorCount==8;
        if(!r.anchorsValid)issues.Add("anchors_invalid");r.goalTriggers=CountTriggers("GoalVolume");r.killTriggers=CountTriggers("KillVolume");r.triggerCountValid=r.goalTriggers==1&&r.killTriggers==1;if(!r.triggerCountValid)issues.Add("trigger_count_invalid");
        r.routeSupported=SupportedSamples(route, 0.5f, ref r.supportSamples);if(!r.routeSupported)issues.Add("route_support_gap");
        var wide = new List<Vector3> { new Vector3(9,0,64), new Vector3(19,0,72), new Vector3(34,0,78), new Vector3(34,0,97), new Vector3(14,0,103), new Vector3(5,0,104) };
        r.wideRouteSupported = SupportedSamples(wide, .5f, ref r.supportSamples);
        if (!r.wideRouteSupported) issues.Add("wide_route_support_gap");
        r.rootIdentity = root != null && root.position == Vector3.zero && root.rotation == Quaternion.identity && root.localScale == Vector3.one;
        if (!r.rootIdentity) issues.Add("environment_root_transform_changed");
        r.visualCollidersAbsent = root != null && root.Find("MinimalArt").GetComponentsInChildren<Collider>(true).Length == 0;
        if (!r.visualCollidersAbsent) issues.Add("visual_collider_present");
        r.rulerSidesClear=RulerSidesClear();if(!r.rulerSidesClear)issues.Add("ruler_side_obstruction");r.dimensionsValid=DimensionsValid();if(!r.dimensionsValid)issues.Add("dimensions_invalid");
        r.noScripts=UnityEngine.Object.FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None).Length==0 && MissingScripts()==0;r.noBodies=UnityEngine.Object.FindObjectsByType<Rigidbody>(FindObjectsSortMode.None).Length==0&&!HasArticulation();if(!r.noScripts)issues.Add("script_or_missing_component_present");if(!r.noBodies)issues.Add("physics_body_present");
        r.prefabReloaded=PrefabReadback();r.sceneReloaded=s.IsValid();if(!r.prefabReloaded)issues.Add("prefab_readback_failed");r.issues=issues.ToArray();return r;
    }
    static int CountTriggers(string n){var o=GameObject.Find(n);return o==null?0:o.GetComponentsInChildren<Collider>(true).Length>0&&o.GetComponent<Collider>()?.isTrigger==true?1:0;}
    static bool HasArticulation(){return UnityEngine.Object.FindObjectsByType<ArticulationBody>(FindObjectsSortMode.None).Length>0;}
    static bool SupportedSamples(List<Vector3> points, float step, ref int samples)
    {
        for (int i = 0; i < points.Count - 1; i++)
        {
            Vector3 a = points[i], b = points[i + 1];
            Vector3 right = Vector3.Cross(Vector3.up, (b - a).normalized);
            int count = Mathf.Max(1, Mathf.CeilToInt(Vector3.Distance(a, b) / step));
            for (int j = 0; j <= count; j++)
            {
                // Approximate 4.4-unit body corridor, not a gait simulation.
                for (int side = -1; side <= 1; side++)
                {
                    Vector3 p = Vector3.Lerp(a, b, j / (float)count) + right * side * 2.2f;
                    samples++;
                    if (!Physics.Raycast(p + Vector3.up, Vector3.down, out var hit, 2f,
                        Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore) || Mathf.Abs(hit.point.y) > .02f)
                    {
                        Debug.LogError("BLIND_STAGE_SUPPORT_GAP position=" + p);
                        return false;
                    }
                }
            }
        }
        return true;
    }
    static bool RulerSidesClear(){for(int i=5;i<=15;i++){Vector3 p=Vector3.Lerp(new Vector3(0,0,29),new Vector3(9,0,53),i/20f);Vector3 d=(new Vector3(9,0,24)).normalized;Vector3 side=Vector3.Cross(Vector3.up,d);for(int k=-1;k<=1;k+=2)if(Physics.Raycast(p+side*k*5+Vector3.up,Vector3.down,2f,Physics.DefaultRaycastLayers,QueryTriggerInteraction.Ignore))return false;}return true;}
    static bool DimensionsValid(){return Size("RulerBridge",8)&&Size("NarrowRoute",6)&&Size("WideRouteA",12)&&Size("WideRouteB",12)&&Size("WideRouteC",12);}
    static bool Size(string n,float expected){var o=GameObject.Find(n);return o!=null&&Mathf.Abs(o.transform.localScale.x-expected)<.01f&&Mathf.Abs(o.transform.position.y+.4f)<.01f;}
    static int MissingScripts(){int n=0;foreach(var t in UnityEngine.Object.FindObjectsByType<Transform>(FindObjectsSortMode.None))foreach(var c in t.GetComponents<Component>())if(c==null)n++;return n;}
    static bool PrefabReadback()
    {
        var root = PrefabUtility.LoadPrefabContents(PrefabPath);
        try
        {
            if (root == null || root.name != "BlindSugarRunEnvironment") return false;
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                foreach (var c in t.GetComponents<Component>())
                    if (c == null || c is MonoBehaviour || c is Rigidbody || c is ArticulationBody) return false;
            return root.transform.Find("Anchors")?.childCount == 8;
        }
        finally { if (root != null) PrefabUtility.UnloadPrefabContents(root); }
    }
    static string GetReportDirectory(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-stageReportPath");return i>=0&&i+1<a.Length&&Path.IsPathRooted(a[i+1])?a[i+1]:Path.GetFullPath(Path.Combine(Application.dataPath,"../../artifacts/blind-sugar-run-stage"));}
    static void Capture(string cameraName, string relative, bool top)
    {
        var o = GameObject.Find(cameraName);
        if (o == null) throw new InvalidOperationException("Capture camera missing: " + cameraName);
        var camera = o.GetComponent<Camera>();
        int width = top ? 900 : 1600;
        int height = top ? 1200 : 1000;
        RenderTexture oldTarget = camera.targetTexture;
        RenderTexture oldActive = RenderTexture.active;
        float oldAspect = camera.aspect;
        var rt = new RenderTexture(width, height, 24);
        Texture2D texture = null;
        try
        {
            rt.Create();
            camera.targetTexture = rt;
            camera.aspect = width / (float)height;
            camera.Render();
            RenderTexture.active = rt;
            texture = new Texture2D(width, height, TextureFormat.RGB24, false);
            texture.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            texture.Apply();
            string dir = GetReportDirectory();
            Directory.CreateDirectory(dir);
            File.WriteAllBytes(Path.Combine(dir, Path.GetFileName(relative)), texture.EncodeToPNG());
        }
        finally
        {
            RenderTexture.active = oldActive;
            camera.targetTexture = oldTarget;
            camera.aspect = oldAspect;
            if (texture != null) UnityEngine.Object.DestroyImmediate(texture);
            rt.Release();
            UnityEngine.Object.DestroyImmediate(rt);
        }
    }
}
