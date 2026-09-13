using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>Bakes non-overlapping exterior support surfaces from BoxCollider geometry.</summary>
public static class BlindSugarRunSurfaceMesh
{
    const float Epsilon = 1e-5f;
    const float AreaEpsilon = 1e-8f;

    struct Face
    {
        public Vector3 normal;
        public Vector3 point;
        public List<Vector3> polygon;
    }

    public static void Bake(GameObject environment, string meshAssetFolder)
    {
        if (environment == null) throw new ArgumentNullException(nameof(environment));
        if (string.IsNullOrWhiteSpace(meshAssetFolder)) throw new ArgumentException("Mesh asset folder is required.", nameof(meshAssetFolder));
        if (!meshAssetFolder.StartsWith("Assets/", StringComparison.Ordinal)) throw new ArgumentException("Mesh asset folder must be under Assets/.", nameof(meshAssetFolder));

        Transform geometry = environment.transform.Find("EnvironmentGeometry");
        if (geometry == null) throw new InvalidOperationException("EnvironmentGeometry was not found.");
        BoxCollider[] boxes = geometry.GetComponentsInChildren<BoxCollider>(true);
        if (boxes.Length == 0) throw new InvalidOperationException("No support BoxCollider was found.");
        Directory.CreateDirectory(Path.GetFullPath(meshAssetFolder));
        AssetDatabase.Refresh();

        for (int i = 0; i < boxes.Length; i++)
        {
            Mesh mesh = BuildMesh(boxes, i);
            string assetPath = meshAssetFolder.TrimEnd('/') + "/" + boxes[i].gameObject.name + ".asset";
            Mesh asset = AssetDatabase.LoadAssetAtPath<Mesh>(assetPath);
            if (asset == null)
            {
                asset = new Mesh { name = boxes[i].gameObject.name };
                AssetDatabase.CreateAsset(asset, assetPath);
            }
            // Mesh API setters update the renderer's native buffers as well as serialized data.
            // CopySerialized alone left the new support assets invisible in this Editor.
            asset.Clear();
            asset.vertices = mesh.vertices;
            asset.triangles = mesh.triangles;
            asset.normals = mesh.normals;
            asset.uv = mesh.uv;
            asset.tangents = mesh.tangents;
            asset.RecalculateBounds();
            asset.UploadMeshData(false);
            asset.name = boxes[i].gameObject.name;
            MeshFilter filter = boxes[i].GetComponent<MeshFilter>() ?? boxes[i].gameObject.AddComponent<MeshFilter>();
            filter.sharedMesh = asset;
            EditorUtility.SetDirty(filter);
            EditorUtility.SetDirty(asset);
            UnityEngine.Object.DestroyImmediate(mesh);
        }
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
    }

    static Mesh BuildMesh(BoxCollider[] boxes, int ownerIndex)
    {
        BoxCollider owner = boxes[ownerIndex];
        List<Vector3> vertices = new List<Vector3>();
        List<int> triangles = new List<int>();
        foreach (Face original in Faces(owner))
        {
            var fragments = new List<List<Vector3>> { original.polygon };
            for (int otherIndex = 0; otherIndex < boxes.Length && fragments.Count > 0; otherIndex++)
            {
                if (otherIndex == ownerIndex) continue;
                var planes = new List<Face>(Faces(boxes[otherIndex]));
                bool ownsCoplanarFace = false;
                foreach (var plane in planes)
                    if (ownerIndex > otherIndex && Vector3.Dot(original.normal, plane.normal) > 1f - Epsilon &&
                        Mathf.Abs(PlaneDistance(original.point, plane)) < Epsilon)
                        ownsCoplanarFace = true;
                if (ownsCoplanarFace) continue;
                var remaining = new List<List<Vector3>>();
                foreach (var fragment in fragments)
                {
                    var inside = fragment;
                    foreach (var plane in planes)
                    {
                        SplitByPlane(inside, plane, out var outside, out inside);
                        if (outside.Count >= 3) remaining.Add(outside);
                        if (inside.Count < 3) break;
                    }
                    // The residue lies inside every half-space of the other box: discard it.
                }
                fragments = remaining;
            }
            foreach (var polygon in fragments)
                AddPolygon(new Face { normal = original.normal, point = original.point, polygon = polygon }, owner.transform, vertices, triangles);
        }
        Mesh mesh = new Mesh { name = owner.gameObject.name + "_SurfaceMesh" };
        mesh.SetVertices(vertices); mesh.SetTriangles(triangles, 0);
        mesh.SetUVs(0, vertices.ConvertAll(v => new Vector2(v.x + v.z, v.y + v.z)));
        mesh.RecalculateNormals(); mesh.RecalculateTangents(); mesh.RecalculateBounds();
        return mesh;
    }

    static void SplitByPlane(List<Vector3> polygon, Face plane, out List<Vector3> outside, out List<Vector3> nextInside)
    {
        outside = new List<Vector3>();
        nextInside = new List<Vector3>();
        if (polygon.Count < 3) return;
        bool anyOutside = false, anyInside = false;
        for (int i = 0; i < polygon.Count; i++)
        {
            float d = Vector3.Dot(plane.normal, polygon[i] - plane.point);
            anyOutside |= d > Epsilon; anyInside |= d < -Epsilon;
        }
        if (!anyOutside) { nextInside.AddRange(polygon); return; }
        if (!anyInside) { outside.AddRange(polygon); return; }
        outside = Clip(polygon, plane, true);
        nextInside = Clip(polygon, plane, false);
    }

    static List<Vector3> Clip(List<Vector3> polygon, Face plane, bool outside)
    {
        List<Vector3> result = new List<Vector3>();
        for (int i = 0; i < polygon.Count; i++)
        {
            Vector3 a = polygon[i], b = polygon[(i + 1) % polygon.Count];
            float da = Vector3.Dot(plane.normal, a - plane.point), db = Vector3.Dot(plane.normal, b - plane.point);
            if (Mathf.Abs(da) < Epsilon) da = 0;
            if (Mathf.Abs(db) < Epsilon) db = 0;
            bool aKept = outside ? da >= 0 : da <= 0;
            bool bKept = outside ? db >= 0 : db <= 0;
            if (aKept) result.Add(a);
            if (aKept != bKept)
            {
                float u = da / (da - db);
                result.Add(Vector3.LerpUnclamped(a, b, u));
            }
        }
        RemoveNearDuplicates(result);
        return result;
    }

    static void AddPolygon(Face face, Transform owner, List<Vector3> vertices, List<int> triangles)
    {
        List<Vector3> p = face.polygon; RemoveNearDuplicates(p);
        if (p.Count < 3 || PolygonArea(p, face.normal) < AreaEpsilon) return;
        int first = vertices.Count;
        for (int i = 0; i < p.Count; i++) vertices.Add(owner.InverseTransformPoint(p[i]));
        for (int i = 1; i + 1 < p.Count; i++) { triangles.Add(first); triangles.Add(first + i); triangles.Add(first + i + 1); }
    }

    static IEnumerable<Face> Faces(BoxCollider box)
    {
        Vector3 c = box.transform.TransformPoint(box.center);
        Vector3[] axis = { box.transform.right.normalized, box.transform.up.normalized, box.transform.forward.normalized };
        Vector3 half = Vector3.Scale(box.size, box.transform.lossyScale) * .5f;
        yield return MakeFace(c + axis[0] * half.x, axis[0], axis[1], axis[2], half.y, half.z);
        yield return MakeFace(c - axis[0] * half.x, -axis[0], axis[1], axis[2], half.y, half.z);
        yield return MakeFace(c + axis[1] * half.y, axis[1], axis[0], axis[2], half.x, half.z);
        yield return MakeFace(c - axis[1] * half.y, -axis[1], axis[0], axis[2], half.x, half.z);
        yield return MakeFace(c + axis[2] * half.z, axis[2], axis[0], axis[1], half.x, half.y);
        yield return MakeFace(c - axis[2] * half.z, -axis[2], axis[0], axis[1], half.x, half.y);
    }

    static Face MakeFace(Vector3 center, Vector3 normal, Vector3 u, Vector3 v, float hu, float hv)
    {
        var polygon = new List<Vector3>{center-u*hu-v*hv,center+u*hu-v*hv,center+u*hu+v*hv,center-u*hu+v*hv};
        if (Vector3.Dot(Vector3.Cross(u,v),normal)<0) polygon.Reverse();
        return new Face { normal=normal, point=center, polygon=polygon };
    }
    static float PlaneDistance(Vector3 p, Face plane){return Vector3.Dot(plane.normal,p-plane.point);}
    static void RemoveNearDuplicates(List<Vector3> p){for(int i=p.Count-1;i>0;i--)if((p[i]-p[i-1]).sqrMagnitude<Epsilon*Epsilon)p.RemoveAt(i);if(p.Count>1&& (p[0]-p[p.Count-1]).sqrMagnitude<Epsilon*Epsilon)p.RemoveAt(p.Count-1);}
    static float PolygonArea(List<Vector3> p,Vector3 n){float area=0;for(int i=1;i+1<p.Count;i++)area+=Vector3.Dot(Vector3.Cross(p[i]-p[0],p[i+1]-p[0]),n);return Mathf.Abs(area)*.5f;}
}
