using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

/// <summary>One-time environment migration and geometry-only verification; never enters Play Mode.</summary>
public static class BlindSugarRunSurfaceRepair
{
    const string PrefabPath = "Assets/BlindSugarRunPrototype/BlindSugarRunEnvironment.prefab";
    const string MeshFolder = "Assets/BlindSugarRunPrototype/SurfaceMeshes";
    static string Reports => Path.GetFullPath(Path.Combine(Application.dataPath, "../../artifacts/blind-sugar-run-surfaces"));
    [Serializable] public class Report
    {
        public int supports, trianglesBefore, trianglesAfter, overlapPairsBefore, overlapPairsAfter, coverageSamples, missingCoverage;
        public float overlapAreaBefore, overlapAreaAfter;
        public bool collidersAndTransformsUnchanged;
        public string status;
    }
    struct Triangle { public Vector2 a, b, c; public int owner; }

    public static void CaptureBefore() => Capture("before");
    public static void CaptureAfter() => Capture("after");
    static void Capture(string label)
    {
        Directory.CreateDirectory(Reports);
        var camera = GameObject.Find("Main Camera").GetComponent<Camera>();
        var position = camera.transform.position; var rotation = camera.transform.rotation;
        var oldTarget = camera.targetTexture; var oldRect = camera.rect;
        var oldFov = camera.fieldOfView; var oldAspect = camera.aspect;
        var oldActive = RenderTexture.active; var oldAsync = ShaderUtil.allowAsyncCompilation;
        var rt = new RenderTexture(1280,720,24); var texture = new Texture2D(1280,720,TextureFormat.RGB24,false);
        try
        {
            ShaderUtil.allowAsyncCompilation = false;
            camera.targetTexture = rt; camera.rect = new Rect(0,0,1,1); camera.aspect=1280f/720; camera.fieldOfView=48;
            var positions = new[] { new Vector3(25,28,2), new Vector3(58,36,65) };
            var targets = new[] { new Vector3(1,0,25), new Vector3(21,0,90) };
            for (int i=0;i<positions.Length;i++)
            {
                camera.transform.position=positions[i]; camera.transform.LookAt(targets[i]);
                camera.Render(); camera.Render(); RenderTexture.active=rt;
                texture.ReadPixels(new Rect(0,0,1280,720),0,0); texture.Apply();
                File.WriteAllBytes(Path.Combine(Reports,label+"-"+(i==0?"ruler":"branch")+".png"),texture.EncodeToPNG());
            }
        }
        finally
        {
            camera.transform.SetPositionAndRotation(position,rotation); camera.targetTexture=oldTarget;
            camera.rect=oldRect; camera.fieldOfView=oldFov; camera.aspect=oldAspect;
            RenderTexture.active=oldActive; ShaderUtil.allowAsyncCompilation=oldAsync;
            UnityEngine.Object.DestroyImmediate(texture); UnityEngine.Object.DestroyImmediate(rt);
        }
    }

    public static void Repair()
    {
        if (EditorApplication.isPlaying) throw new InvalidOperationException("Exit Play Mode first.");
        Directory.CreateDirectory(Reports);
        var root = PrefabUtility.LoadPrefabContents(PrefabPath);
        try
        {
            var geometry = root.transform.Find("EnvironmentGeometry");
            var protectedComponents = root.GetComponentsInChildren<Component>(true)
                .Where(c => c != null && !(c is MeshFilter))
                .ToDictionary(c => c, c => EditorJsonUtility.ToJson(c));
            var r = new Report { supports = geometry.childCount };
            var before = TopTriangles(geometry);
            r.trianglesBefore = before.Count;
            Overlaps(before, out r.overlapPairsBefore, out r.overlapAreaBefore);
            BlindSugarRunSurfaceMesh.Bake(root, MeshFolder);
            r.collidersAndTransformsUnchanged = protectedComponents.All(e => e.Key != null && EditorJsonUtility.ToJson(e.Key) == e.Value);
            var after = TopTriangles(geometry);
            r.trianglesAfter = after.Count;
            Overlaps(after, out r.overlapPairsAfter, out r.overlapAreaAfter);
            // Independent point coverage against the unchanged support boxes, away from exact boundary coordinates.
            var boxes = geometry.GetComponentsInChildren<BoxCollider>();
            for (float x = -14.127f; x < 42; x += .5f)
                for (float z = -12.173f; z < 115; z += .5f)
                {
                    var p = new Vector3(x, -.0001f, z);
                    bool supported = boxes.Any(box => {
                        var local = box.transform.InverseTransformPoint(p) - box.center;
                        var half = box.size * .5f;
                        return Mathf.Abs(local.x) < half.x && Mathf.Abs(local.y) < half.y && Mathf.Abs(local.z) < half.z;
                    });
                    if (!supported) continue;
                    r.coverageSamples++;
                    if (!after.Any(t => Contains(t, new Vector2(x,z)))) r.missingCoverage++;
                }
            r.status = r.collidersAndTransformsUnchanged && r.overlapPairsAfter == 0 && r.missingCoverage == 0 ? "PASS" : "FAIL";
            File.WriteAllText(Path.Combine(Reports, "geometry-validation.json"), JsonUtility.ToJson(r, true));
            if (r.status != "PASS") throw new InvalidOperationException("Surface validation failed; prefab was not saved.");
            PrefabUtility.SaveAsPrefabAsset(root, PrefabPath);
            AssetDatabase.SaveAssets();
            Debug.Log("BLIND_SUGAR_SURFACES_PASS " + JsonUtility.ToJson(r));
        }
        finally { PrefabUtility.UnloadPrefabContents(root); }
    }

    static List<Triangle> TopTriangles(Transform geometry)
    {
        var result = new List<Triangle>();
        for (int owner = 0; owner < geometry.childCount; owner++)
        {
            var tr = geometry.GetChild(owner); var mesh = tr.GetComponent<MeshFilter>().sharedMesh;
            var v = mesh.vertices; var indices = mesh.triangles;
            for (int i = 0; i < indices.Length; i += 3)
            {
                var a = tr.TransformPoint(v[indices[i]]); var b = tr.TransformPoint(v[indices[i+1]]); var c = tr.TransformPoint(v[indices[i+2]]);
                if (Mathf.Abs(a.y) > .0002f || Mathf.Abs(b.y) > .0002f || Mathf.Abs(c.y) > .0002f) continue;
                var triangle = new Triangle { a = new Vector2(a.x,a.z), b = new Vector2(b.x,b.z), c = new Vector2(c.x,c.z), owner = owner };
                if (Cross(triangle.b-triangle.a, triangle.c-triangle.a) < 0) { var swap = triangle.b; triangle.b = triangle.c; triangle.c = swap; }
                result.Add(triangle);
            }
        }
        return result;
    }
    static float Cross(Vector2 a, Vector2 b) => a.x*b.y-a.y*b.x;
    static bool Contains(Triangle t, Vector2 p) => Cross(t.b-t.a,p-t.a)>=-1e-5f && Cross(t.c-t.b,p-t.b)>=-1e-5f && Cross(t.a-t.c,p-t.c)>=-1e-5f;
    static void Overlaps(List<Triangle> triangles, out int pairs, out float totalArea)
    {
        pairs=0; totalArea=0;
        for (int i=0;i<triangles.Count;i++) for(int j=i+1;j<triangles.Count;j++)
        {
            if(triangles[i].owner==triangles[j].owner) continue;
            var subject=triangles[i]; var clip=triangles[j];
            var polygon=new List<Vector2>{subject.a,subject.b,subject.c};
            var edges=new[]{clip.a,clip.b,clip.c};
            for(int k=0;k<3 && polygon.Count>0;k++)
            {
                var a=edges[k]; var b=edges[(k+1)%3]; var output=new List<Vector2>();
                for(int n=0;n<polygon.Count;n++)
                {
                    var p=polygon[n]; var q=polygon[(n+1)%polygon.Count];
                    float dp=Cross(b-a,p-a), dq=Cross(b-a,q-a);
                    if(dp>=0) output.Add(p);
                    if((dp>=0)!=(dq>=0)) output.Add(Vector2.LerpUnclamped(p,q,dp/(dp-dq)));
                }
                polygon=output;
            }
            // Translate before the shoelace sum to avoid cancellation at distant stage coordinates.
            float area=0;
            for(int n=1;n+1<polygon.Count;n++) area+=Cross(polygon[n]-polygon[0],polygon[n+1]-polygon[0])*.5f;
            if(area>.0002f) { pairs++; totalArea+=area; }
        }
    }
}
