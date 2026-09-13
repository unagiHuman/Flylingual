using System;
using System.IO;
using Flylingual.Conversation;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace FlyLocomotionPoC
{
    // Installed only for the grounded candidate rig; no scene or source rig mutation.
    public sealed class FlyTerrainRuntime : MonoBehaviour
    {
        FlyBody body;
        FlyLocomotionController controller;
        FlyTerrainSensor sensor;
        FlyTerrainTraversal traversal;
        ConversationSessionController conversation;
        float nextReport, nextDiscovery;
        StreamWriter log;
        int epoch = -1, generation = -1, wireSequence;
        Vector3 travelAnchor, previousPosition;
        double travelMeters;
        bool travelInitialized, travelValid = true;
        public double TravelMeters => travelInitialized && travelValid ? travelMeters : -1;
        public float HorizontalSpeedMetersPerSecond => body == null ? -1 : Vector3.ProjectOnPlane(body.LinearVelocity, Vector3.up).magnitude;
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Register()
        {
            SceneManager.sceneLoaded -= Loaded;
            SceneManager.sceneLoaded += Loaded;
        }
        static void Loaded(Scene scene, LoadSceneMode mode)
        {
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-disableTerrainSensing") >= 0) return;
            foreach (var b in FindObjectsByType<FlyBody>(FindObjectsInactive.Exclude))
                if (b.Config != null && b.Config.groundedTripodGait && b.GetComponent<FlyTerrainRuntime>() == null)
                    b.gameObject.AddComponent<FlyTerrainRuntime>();
        }
        void Start()
        {
            body = GetComponent<FlyBody>(); controller = GetComponent<FlyLocomotionController>();
            if (body == null || controller == null) { enabled = false; return; }
            sensor = GetComponent<FlyTerrainSensor>() ?? gameObject.AddComponent<FlyTerrainSensor>(); sensor.Configure(body);
            traversal = GetComponent<FlyTerrainTraversal>() ?? gameObject.AddComponent<FlyTerrainTraversal>(); traversal.Configure(body, sensor, controller);
            controller.SetTerrainTraversal(traversal);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-terrainLog") >= 0)
            {
                string output = FlyVisualDemo.WindowsReplayDemo.Argument("-demoOutput");
                if (string.IsNullOrEmpty(output)) output = Application.persistentDataPath;
                Directory.CreateDirectory(output);
                log = new StreamWriter(Path.Combine(output, "terrain-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff") + ".jsonl")) { AutoFlush = true };
            }
            Debug.Log("FLY_TERRAIN_READY legs=" + body.Legs.Count + " maxStep=" + sensor.MaximumStep);
        }
        void Update()
        {
            if (sensor == null || Time.unscaledTime < nextReport) return;
            nextReport = Time.unscaledTime + .1f;
            if (conversation == null && Time.unscaledTime >= nextDiscovery)
            { nextDiscovery = Time.unscaledTime + 1f; conversation = FindAnyObjectByType<ConversationSessionController>(); }
            var o = sensor.Observation;
            if (conversation != null && o != null && sensor.Fresh)
            {
                if (epoch != conversation.ControlEpoch || generation != conversation.ConversationGeneration)
                {
                    epoch = conversation.ControlEpoch; generation = conversation.ConversationGeneration; wireSequence = 0;
                    travelMeters = 0; travelAnchor = previousPosition = body.Position; travelInitialized = travelValid = true;
                }
                conversation.SendLocalSafetyObservation(++wireSequence, Mathf.Max(0f, (Time.unscaledTime - o.sampledAt) * 1000f),
                    o.groundPresent && !o.queryOverflow, o.queryOverflow ? "unknown" : o.leftEdge, o.queryOverflow ? "unknown" : o.rightEdge,
                    o.forwardBlocked, o.bodyUnsafe, TravelMeters, HorizontalSpeedMetersPerSecond);
            }
            if (log != null)
            {
                var live = controller.MotorSource as BrainMotorSource;
                log.WriteLine(JsonUtility.ToJson(new Trace { time = Time.unscaledTime, observation = o, feet = traversal.Feet,
                    bodyPosition = body.Position, bodyVelocity = body.LinearVelocity, phase = controller.Phase,
                    hold = traversal.SafetyHold, reason = traversal.Reason, postureLift = traversal.PostureLift, brainSequence = live?.LatestFrame?.sequence ?? -1,
                    forward = live?.LatestFrame?.motor?.forward ?? 0f, turn = live?.LatestFrame?.motor?.turn ?? 0f }));
            }
        }
        void FixedUpdate()
        {
            if (body == null || controller == null || !travelInitialized || !travelValid) return;
            Vector3 position = body.Position;
            if (float.IsNaN(position.x) || float.IsNaN(position.z) || float.IsInfinity(position.x) || float.IsInfinity(position.z))
            { travelValid = false; return; }
            Vector3 tickDelta = Vector3.ProjectOnPlane(position - previousPosition, Vector3.up);
            previousPosition = position;
            // Teleports are not walking. A generation reset starts a new odometer.
            if (tickDelta.magnitude > Mathf.Max(1f, Time.fixedDeltaTime * 5f))
            { travelValid = false; return; }
            var motor = controller.CurrentMotor;
            // Continue measuring physical coasting after the neural motor settles.
            if (Mathf.Max(Mathf.Abs(motor.forward), Mathf.Abs(motor.turn)) < .001f && HorizontalSpeedMetersPerSecond < .03f)
            { travelAnchor = position; return; }
            // Integrate horizontal travel in 1 cm segments, suppressing stationary
            // body jitter and excluding vertical bobbing. Values are Unity metres.
            float segment = Vector3.ProjectOnPlane(position - travelAnchor, Vector3.up).magnitude;
            if (segment >= .01f) { travelMeters += segment; travelAnchor = position; }
        }
        [Serializable] sealed class Trace
        {
            public float time, phase, forward, turn, postureLift;
            public int brainSequence;
            public bool hold;
            public string reason;
            public Vector3 bodyPosition, bodyVelocity;
            public FlyWorldObservation observation;
            public FlyTerrainFootState[] feet;
        }
        void OnDestroy() { if (controller != null) controller.SetTerrainTraversal(null); log?.Dispose(); }
    }
}
