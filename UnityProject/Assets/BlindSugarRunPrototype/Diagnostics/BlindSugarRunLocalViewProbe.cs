#if UNITY_EDITOR || DEVELOPMENT_BUILD
using System;
using System.Collections;
using System.IO;
using System.Linq;
using Flylingual.Conversation;
using Flylingual.PlayScreen;
using UnityEngine;
using UnityEngine.UIElements;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Opt-in passive observation of the actual Player UI and Windows Brain connection.</summary>
    public sealed class BlindSugarRunLocalViewProbe : MonoBehaviour
    {
        [Serializable] public class Report
        {
            public string status, backend, error, runDirectory;
            public bool rawBrainReady, localViewActive, gameImageVisible, bodyActive;
            public int freshSamples, samples = 30, firstSequence, lastSequence;
            public int visibleGamePixels;
            public bool cameraEnabled, spotlightEnabled;
            public bool toggleTested, overviewViaDigit1, localViaNumpad1;
            public bool minimapTested, minimapVisible, explorationRetained, debugDidNotRevealMap;
            public int initialMapCells, finalMapCells, visitedCells, knownCliffEdges;
            public float mapWalkDistance;
            public float radius, maxSpotlightTrackingError;
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-blindSugarLocalViewProbe") >= 0)
                new GameObject("Local View Acceptance Recorder").AddComponent<BlindSugarRunLocalViewProbe>();
        }

        IEnumerator Start()
        {
            var args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, "-blindSugarLocalViewProbe");
            if (index + 1 >= args.Length) yield break;
            string directory = Path.GetFullPath(args[index + 1]);
            Directory.CreateDirectory(directory);
            var report = new Report();
            ConversationSessionController controller = null;
            NativeConversationBody body = null;
            float deadline = Time.realtimeSinceStartup + 90f;
            while (Time.realtimeSinceStartup < deadline)
            {
                controller = FindAnyObjectByType<ConversationSessionController>();
                body = controller == null ? null : controller.GetComponent<NativeConversationBody>();
                if (body != null && body.BodyActive && controller.HasFreshBrain) break;
                yield return null;
            }
            var visibility = FindAnyObjectByType<BlindSugarRunLocalVisibility>();
            var view = FindAnyObjectByType<PlayScreenView>();
            report.backend = controller?.Backend;
            report.rawBrainReady = controller != null && controller.BrainReady;
            report.bodyActive = body != null && body.BodyActive;
            report.firstSequence = body == null ? -1 : body.TcpSequence;
            report.runDirectory = FindAnyObjectByType<ConversationNativeBootstrap>()?.RunDirectory;
            report.localViewActive = visibility != null && visibility.LocalViewActive;
            report.radius = visibility == null ? 0 : visibility.visibleRadius;
            for (int i = 0; i < report.samples; i++)
            {
                if (controller != null && controller.HasFreshBrain) report.freshSamples++;
                if (visibility != null && visibility.spotlight != null)
                    report.maxSpotlightTrackingError = Mathf.Max(report.maxSpotlightTrackingError,
                        Vector3.Distance(visibility.spotlight.transform.position, visibility.follow.position + Vector3.up * visibility.lightHeight));
                yield return new WaitForSecondsRealtime(.2f);
            }
            report.lastSequence = body == null ? -1 : body.TcpSequence;
            report.error = controller == null ? "controller_missing" : controller.Error ?? controller.SchemaError;
            Transform fixtureFloor = null;
            Vector3 fixturePosition = default, fixtureScale = default;
            if (Array.IndexOf(args, "-blindSugarMinimapProbe") >= 0)
            {
                var map = FindAnyObjectByType<BlindSugarRunExplorationMap>();
                report.minimapTested = map != null && map.MappingActive && controller != null && controller.BodyControlActive;
                if (report.minimapTested)
                {
                    report.initialMapCells = map.Cells.Count;
                    var initialCells = map.Cells.Keys.ToArray();
                    Vector3 from = map.PlayerPosition;
                    controller.SendPlayerText("5m前に進んで");
                    float until = Time.realtimeSinceStartup + 35f;
                    while (Time.realtimeSinceStartup < until)
                    {
                        report.mapWalkDistance = Vector3.Distance(from, map.PlayerPosition);
                        if (report.mapWalkDistance > 3.5f && map.stage.fly.LinearVelocity.magnitude < .06f) break;
                        yield return new WaitForSecondsRealtime(.2f);
                    }
                    controller.EmergencyStop();
                    yield return new WaitForSecondsRealtime(.5f);
                    report.finalMapCells = map.Cells.Count;
                    report.visitedCells = map.Cells.Values.Count(cell => cell.visited);
                    report.explorationRetained = initialCells.All(key => map.Cells.ContainsKey(key));
                    int beforeOverview = map.Cells.Count;
                    visibility.ToggleDebugOverview(); yield return new WaitForSecondsRealtime(.5f);
                    report.debugDidNotRevealMap = map.Cells.Count <= beforeOverview + 4;
                    visibility.ToggleDebugOverview();
                    // A reversible, explicit terrain fixture creates a locally visible ledge ahead.
                    // The fly is already stopped through the existing control route; no body teleport or motor injection.
                    fixtureFloor = GameObject.Find("BlindSugarRunEnvironment")?.transform.Find("EnvironmentGeometry/StartArea");
                    if (fixtureFloor != null)
                    {
                        fixturePosition = fixtureFloor.position; fixtureScale = fixtureFloor.localScale;
                        var bounds = fixtureFloor.GetComponent<Collider>().bounds;
                        float edgeZ = map.PlayerPosition.z + 1.9f;
                        var scale = fixtureScale; scale.z *= (edgeZ - bounds.min.z) / bounds.size.z;
                        fixtureFloor.localScale = scale;
                        var position = fixturePosition; position.z += (edgeZ - bounds.max.z) * .5f; fixtureFloor.position = position;
                        Physics.SyncTransforms();
                        yield return new WaitForSecondsRealtime(.6f);
                        var sides = new[] { Vector2Int.up, Vector2Int.down, Vector2Int.left, Vector2Int.right };
                        report.knownCliffEdges = map.Cells.Where(cell => cell.Value.ground).Sum(cell => sides.Count(side =>
                            map.Cells.TryGetValue(cell.Key + side, out var other) && !other.ground));
                    }
                    report.minimapVisible = map.GetComponent<BlindSugarRunMinimapView>()?.Visible ?? false;
                    File.WriteAllText(Path.Combine(directory,"map-cells.json"), "[" + string.Join(",", map.Cells.Select(cell =>
                        "{\"x\":" + cell.Key.x + ",\"z\":" + cell.Key.y + ",\"ground\":" + (cell.Value.ground ? "true" : "false") +
                        ",\"visited\":" + (cell.Value.visited ? "true" : "false") + "}")) + "]");
                }
            }
            // Hidden Windows Players can skip automatic camera rendering. Render the actual cameras
            // explicitly for capture; no scene transforms, materials, lighting or body state are changed.
            foreach (var camera in FindObjectsByType<Camera>())
                if (camera.enabled && camera.targetTexture != null) { camera.Render(); camera.Render(); }
            if (visibility != null && visibility.stageCamera.targetTexture != null)
            {
                report.cameraEnabled = visibility.stageCamera.enabled;
                report.spotlightEnabled = visibility.spotlight.enabled;
                report.visibleGamePixels = Capture(visibility.stageCamera.targetTexture, Path.Combine(directory, "game-view.png"));
            }
            if (view != null)
            {
                var document = view.GetComponent<UIDocument>();
                var settings = document.panelSettings;
                var oldTarget = settings.targetTexture;
                var target = new RenderTexture(1280,720,24); target.Create(); settings.targetTexture = target;
                yield return null; yield return null; yield return null;
                var image = document.rootVisualElement.Query<Image>().ToList().Find(element => visibility != null && element.image == visibility.stageCamera.targetTexture);
                report.gameImageVisible = image != null && image.resolvedStyle.display == DisplayStyle.Flex && image.worldBound.width > 0 && image.worldBound.height > 0;
                Capture(target, Path.Combine(directory,"play-screen.png"));
                settings.targetTexture = oldTarget; target.Release(); Destroy(target);
            }
            if (Array.IndexOf(args, "-blindSugarToggleProbe") >= 0 && Keyboard.current != null && visibility != null)
            {
                report.toggleTested = true;
                yield return PressKey(Key.Digit1);
                report.overviewViaDigit1 = visibility.DebugOverviewActive && !visibility.LocalViewActive && !visibility.spotlight.enabled;
                visibility.stageCamera.Render();
                Capture(visibility.stageCamera.targetTexture, Path.Combine(directory, "debug-overview.png"));
                yield return PressKey(Key.Numpad1);
                report.localViaNumpad1 = !visibility.DebugOverviewActive && visibility.LocalViewActive && visibility.spotlight.enabled;
                visibility.stageCamera.Render();
                Capture(visibility.stageCamera.targetTexture, Path.Combine(directory, "debug-local-restored.png"));
            }
            report.status = report.localViewActive && report.gameImageVisible && report.bodyActive && report.lastSequence > report.firstSequence
                && report.freshSamples > 0 && report.maxSpotlightTrackingError < .05f && report.visibleGamePixels > 1000 ? "PASS" : "FAIL";
            if (Array.IndexOf(args, "-blindSugarToggleProbe") >= 0 && (!report.toggleTested || !report.overviewViaDigit1 || !report.localViaNumpad1)) report.status = "FAIL";
            if (Array.IndexOf(args, "-blindSugarMinimapProbe") >= 0 && (!report.minimapTested || !report.minimapVisible ||
                !report.explorationRetained || !report.debugDidNotRevealMap || report.finalMapCells <= report.initialMapCells ||
                report.visitedCells < 2 || report.mapWalkDistance < 1f || report.knownCliffEdges < 1)) report.status = "FAIL";
            if (fixtureFloor != null)
            { fixtureFloor.position = fixturePosition; fixtureFloor.localScale = fixtureScale; Physics.SyncTransforms(); }
            File.WriteAllText(Path.Combine(directory,"report.json"),JsonUtility.ToJson(report,true));
            Debug.Log("BLIND_SUGAR_LOCAL_VIEW_PROBE " + JsonUtility.ToJson(report));
            Application.Quit(report.status == "PASS" ? 0 : 1);
        }

        static IEnumerator PressKey(Key key)
        {
            // Exercises the same Input System binding as the physical keyboard, inside this Player only.
            InputSystem.QueueStateEvent(Keyboard.current, new KeyboardState(key));
            yield return null; yield return null;
            InputSystem.QueueStateEvent(Keyboard.current, new KeyboardState());
            yield return null; yield return null;
        }

        static int Capture(RenderTexture source, string path)
        {
            var previous = RenderTexture.active; RenderTexture.active = source;
            var texture = new Texture2D(source.width,source.height,TextureFormat.RGB24,false);
            texture.ReadPixels(new Rect(0,0,source.width,source.height),0,0); texture.Apply();
            File.WriteAllBytes(path,texture.EncodeToPNG());
            int visible = 0;
            foreach (var pixel in texture.GetPixels32()) if (pixel.r > 16 || pixel.g > 16 || pixel.b > 16) visible++;
            RenderTexture.active = previous; Destroy(texture);
            return visible;
        }
    }
}
#endif
