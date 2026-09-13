using System;
using System.Collections.Generic;
using Flylingual.PlayScreen;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.InputSystem;
using UnityEngine.UIElements;

namespace Flylingual.BlindSugarRun
{
    /// <summary>Presentation only: a soft pool of light follows the fly, with no distant world lighting.</summary>
    [DefaultExecutionOrder(300)]
    [DisallowMultipleComponent]
    public sealed class BlindSugarRunLocalVisibility : MonoBehaviour
    {
        public Transform follow;
        public Camera stageCamera;
        public Light spotlight;
        [Min(.5f)] public float visibleRadius = 3f;
        [Min(1f)] public float lightHeight = 8f;
        [Min(0f)] public float lightIntensity = 180f;
        public Vector3 cameraOffset = new Vector3(4f, 7f, -7f);
        public Vector3 cameraFocus = new Vector3(0f, -.5f, 0f);
        [Range(20f, 80f)] public float fieldOfView = 43f;

        readonly Dictionary<Light, bool> oldLights = new Dictionary<Light, bool>();
        AmbientMode oldAmbientMode;
        Color oldAmbient, oldSky, oldEquator, oldGround, oldBackground;
        Material oldSkybox;
        float oldAmbientIntensity, oldReflectionIntensity, oldFov;
        bool oldFog;
        CameraClearFlags oldClearFlags;
        bool applied;
        BlindSugarRunSession session;
        public bool LocalViewActive => applied;
        public bool DebugOverviewActive { get; private set; }
        Vector3 overviewPosition, overviewFocus;

        void Start()
        {
            session = FindAnyObjectByType<BlindSugarRunSession>();
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-blindSugarDeveloperView") >= 0) return;
            ApplyLocalView();
        }

        void Update()
        {
            var keyboard = Keyboard.current;
            if (keyboard == null || keyboard.ctrlKey.isPressed || keyboard.altKey.isPressed || keyboard.shiftKey.isPressed) return;
            if (!keyboard.digit1Key.wasPressedThisFrame && !keyboard.numpad1Key.wasPressedThisFrame) return;
            foreach (var document in FindObjectsByType<UIDocument>())
            {
                var focused = document.rootVisualElement?.focusController?.focusedElement as VisualElement;
                if (focused is TextField || focused?.GetFirstAncestorOfType<TextField>() != null) return;
            }
            ToggleDebugOverview();
        }

        public bool ToggleDebugOverview()
        {
            if (follow == null || stageCamera == null || spotlight == null ||
                (session != null && (session.State == BlindSugarRunSession.StageState.Goal || session.State == BlindSugarRunSession.StageState.Reveal))) return false;
            if (DebugOverviewActive)
            {
                DebugOverviewActive = false;
                ApplyLocalView();
            }
            else
            {
                RestoreView();
                var bounds = new Bounds(follow.position, Vector3.one * 4f);
                foreach (var root in gameObject.scene.GetRootGameObjects())
                {
                    var geometry = root.transform.Find("EnvironmentGeometry");
                    if (geometry == null) continue;
                    foreach (var renderer in geometry.GetComponentsInChildren<Renderer>())
                        if (renderer.enabled && renderer.name != "CatchRecovery") bounds.Encapsulate(renderer.bounds);
                }
                overviewFocus = bounds.center;
                float halfVertical = stageCamera.fieldOfView * Mathf.Deg2Rad * .5f;
                float halfHorizontal = Mathf.Atan(Mathf.Tan(halfVertical) * stageCamera.aspect);
                float distance = bounds.extents.magnitude / Mathf.Sin(Mathf.Min(halfVertical, halfHorizontal)) * 1.1f;
                overviewPosition = overviewFocus + new Vector3(.35f, .9f, -1f).normalized * distance;
                DebugOverviewActive = true;
                FindAnyObjectByType<PlayScreenView>()?.SetBlindMode(false);
            }
            UpdateView();
            Debug.Log("BLIND_SUGAR_DEBUG_OVERVIEW enabled=" + DebugOverviewActive);
            return true;
        }

        public void ApplyLocalView()
        {
            if (applied || follow == null || stageCamera == null || spotlight == null) return;
            oldAmbientMode = RenderSettings.ambientMode;
            oldAmbient = RenderSettings.ambientLight;
            oldSky = RenderSettings.ambientSkyColor; oldEquator = RenderSettings.ambientEquatorColor;
            oldGround = RenderSettings.ambientGroundColor; oldSkybox = RenderSettings.skybox;
            oldAmbientIntensity = RenderSettings.ambientIntensity; oldReflectionIntensity = RenderSettings.reflectionIntensity;
            oldFog = RenderSettings.fog;
            oldBackground = stageCamera.backgroundColor; oldClearFlags = stageCamera.clearFlags; oldFov = stageCamera.fieldOfView;
            foreach (var light in FindObjectsByType<Light>())
            {
                if (light == spotlight || light.gameObject.scene != gameObject.scene) continue;
                oldLights[light] = light.enabled;
                light.enabled = false;
            }
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = Color.black;
            RenderSettings.ambientSkyColor = RenderSettings.ambientEquatorColor = RenderSettings.ambientGroundColor = Color.black;
            RenderSettings.ambientIntensity = RenderSettings.reflectionIntensity = 0f;
            RenderSettings.skybox = null;
            RenderSettings.fog = false;
            stageCamera.clearFlags = CameraClearFlags.SolidColor;
            stageCamera.backgroundColor = Color.black;
            spotlight.type = LightType.Spot;
            spotlight.color = new Color(1f, .94f, .82f);
            spotlight.shadows = LightShadows.Soft;
            spotlight.shadowBias = .025f;
            spotlight.shadowNormalBias = .1f;
            spotlight.cullingMask = ~(1 << 31); // The separate neural display keeps its own presentation.
            spotlight.enabled = true;
            applied = true;
            UpdateView();
            // PlayScreenRuntime has finished creating the UI before this component's Start (order 300).
            FindAnyObjectByType<PlayScreenView>()?.SetBlindMode(false);
            Debug.Log("BLIND_SUGAR_LOCAL_VIEW radius=" + visibleRadius + " camera=world spotlight=following");
        }

        public void UpdateView()
        {
            if (DebugOverviewActive && stageCamera != null)
            {
                stageCamera.transform.position = overviewPosition;
                stageCamera.transform.LookAt(overviewFocus);
                return;
            }
            if (!applied || follow == null || stageCamera == null || spotlight == null) return;
            stageCamera.fieldOfView = fieldOfView;
            stageCamera.transform.position = follow.position + cameraOffset;
            stageCamera.transform.LookAt(follow.position + cameraFocus);
            spotlight.transform.SetPositionAndRotation(follow.position + Vector3.up * lightHeight, Quaternion.Euler(90f, 0f, 0f));
            // Grounded thorax clearance is about 1.1 units; the light's ground footprint has ~3m radius.
            float groundDistance = lightHeight + 1.1f;
            spotlight.spotAngle = 2f * Mathf.Atan(visibleRadius / groundDistance) * Mathf.Rad2Deg;
            spotlight.innerSpotAngle = spotlight.spotAngle * .76f;
            spotlight.range = groundDistance + 3f;
            spotlight.intensity = lightIntensity;
        }

        void LateUpdate()
        {
            // The existing goal reveal owns the camera and must be able to show the whole course.
            if (session != null && (session.State == BlindSugarRunSession.StageState.Goal || session.State == BlindSugarRunSession.StageState.Reveal))
            { DebugOverviewActive = false; RestoreView(); return; }
            UpdateView();
        }

        public void RestoreView()
        {
            if (!applied) return;
            applied = false;
            if (spotlight != null) spotlight.enabled = false;
            foreach (var pair in oldLights) if (pair.Key != null) pair.Key.enabled = pair.Value;
            oldLights.Clear();
            RenderSettings.ambientMode = oldAmbientMode; RenderSettings.ambientLight = oldAmbient;
            RenderSettings.ambientSkyColor = oldSky; RenderSettings.ambientEquatorColor = oldEquator; RenderSettings.ambientGroundColor = oldGround;
            RenderSettings.ambientIntensity = oldAmbientIntensity; RenderSettings.reflectionIntensity = oldReflectionIntensity;
            RenderSettings.skybox = oldSkybox; RenderSettings.fog = oldFog;
            if (stageCamera != null)
            { stageCamera.backgroundColor = oldBackground; stageCamera.clearFlags = oldClearFlags; stageCamera.fieldOfView = oldFov; }
        }

        void OnDisable() => RestoreView();
    }
}
