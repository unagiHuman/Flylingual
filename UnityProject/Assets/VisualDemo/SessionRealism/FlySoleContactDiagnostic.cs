using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using FlyBrainPoC;
using FlyLocomotionPoC;
using UnityEngine;

namespace FlyVisualDemo
{
    // Opt-in, passive evidence capture for investigating visual sole placement
    // against the existing physical FootPad contacts. It never writes a motor,
    // drive, transform, collider, or physics setting.
    [DefaultExecutionOrder(1000)]
    public sealed class FlySoleContactDiagnostic : MonoBehaviour
    {
        [Serializable]
        sealed class SessionRow
        {
            public string kind = "sole-contact-session";
            public string utc;
            public int articulationJoints;
            public int footPads;
            public string endpoint;
            public string mode;
        }

        [Serializable]
        sealed class TickRow
        {
            public string kind = "sole-contact-tick";
            public string utc;
            public int tick;
            public float fixedTime;
            public int articulationJoints;
            public int footPads;
            public Vector3 bodyPosition;
            public Vector3 bodyVelocity;
            public float phase;
            public LegRow[] legs;
            public CollisionRow[] collisions;
            public LiveRow live;
        }

        [Serializable]
        sealed class LegRow
        {
            public string leg;
            public bool commandStance;
            public bool evaluatedStance;
            public bool attached;
            public bool freshFootContact;
            public string contactSource;
            public int contactHoldTicks;
            public string otherCollider;
            public Vector3 contactPoint;
            public Vector3 contactNormal;
            public float footColliderMinY;
            public float femurCapsuleMinY;
            public float tibiaCapsuleMinY;
            public Vector3 kneePosition, footCenter, visibleSole;
            public float soleContactNormalError;
            public Vector3 footBoundsExtents;
            public JointRow coxa;
            public JointRow femur;
            public JointRow tibia;
        }

        [Serializable]
        sealed class JointRow
        {
            public float appliedTargetDegrees;
            public float driveTargetDegrees;
            public float actualDegrees;
            public float velocityDegreesPerSecond;
        }

        [Serializable]
        sealed class CollisionRow
        {
            public string eventType;
            public float observedFixedTime;
            public string classification;
            public string leg;
            public string owner;
            public string ownCollider;
            public string otherCollider;
            public Vector3 point;
            public Vector3 normal;
            public Vector3 impulse;
            public Vector3 relativeVelocity;
        }

        [Serializable]
        sealed class LiveRow
        {
            public string endpoint;
            public string connectionState;
            public string backend;
            public bool ready;
            public int sequence;
            public float frameAgeSeconds;
            public bool stale;
            public string protocolError;
            public int observedProtocolErrorCount;
            public int replayIndex;
            public int replayFrameCount;
        }

        [Serializable]
        sealed class SummaryRow
        {
            public string kind = "sole-contact-summary";
            public string utc;
            public int tickCount;
            public int footCollisionCount;
            public int nonFootCollisionCount;
            public int observedProtocolErrorCount;
            public int articulationJoints;
            public int footPads;
        }

        WindowsReplayDemo demo;
        FlyBody body;
        StreamWriter writer;
        readonly List<CollisionRow> collisions = new List<CollisionRow>();
        readonly Dictionary<Collider, FlyLeg> feet = new Dictionary<Collider, FlyLeg>();
        readonly Dictionary<FlyLeg, FlyLeg.LegDriveTarget> targets = new Dictionary<FlyLeg, FlyLeg.LegDriveTarget>();
        readonly Dictionary<FlyLeg, FlySoleVisualEndpoint> soles = new Dictionary<FlyLeg, FlySoleVisualEndpoint>();
        string outputDirectory;
        int ticks;
        int footCollisions;
        int nonFootCollisions;
        int observedProtocolErrors;
        string lastProtocolError = string.Empty;
        bool closed;
        float nextCapture;
        int captureIndex;

        void LateUpdate()
        {
            if (writer == null || !WindowsReplayDemo.Flag("-soleRecord") || Time.unscaledTime < nextCapture) return;
            nextCapture = Time.unscaledTime + .2f;
            ScreenCapture.CaptureScreenshot(Path.Combine(outputDirectory, "sole-frame-" + (captureIndex++).ToString("D5") + ".png"));
        }

        void Awake()
        {
            demo = GetComponent<WindowsReplayDemo>();
            if (demo == null)
            {
                Debug.LogError("SOLE_CONTACT_DIAGNOSTIC requires WindowsReplayDemo.", this);
                enabled = false;
                return;
            }
            body = demo.body;
            if (body == null)
            {
                Debug.LogError("SOLE_CONTACT_DIAGNOSTIC requires FlyBody.", this);
                enabled = false;
                return;
            }

            outputDirectory = WindowsReplayDemo.Argument("-demoOutput");
            if (string.IsNullOrWhiteSpace(outputDirectory))
            {
                Debug.LogError("SOLE_CONTACT_DIAGNOSTIC requires an explicit -demoOutput session directory.", this);
                enabled = false;
                return;
            }
            outputDirectory = Path.GetFullPath(outputDirectory);
            Directory.CreateDirectory(outputDirectory);
            writer = new StreamWriter(Path.Combine(outputDirectory, "sole-contact.jsonl")) { AutoFlush = true };

            foreach (FlyLeg leg in body.Legs)
            {
                if (leg == null || leg.FootContact == null) continue;
                Collider foot = leg.FootContact.GetComponent<Collider>();
                if (foot != null) feet[foot] = leg;
                var sole = demo.visualRig.GetComponentsInChildren<FlySoleVisualEndpoint>().FirstOrDefault(s => s.contact == leg.FootContact);
                if (sole != null) soles[leg] = sole;
            }
            if (demo.controller != null) demo.controller.DiagnosticTargetObserved += ObserveTarget;
            foreach (ArticulationBody owner in body.GetComponentsInChildren<ArticulationBody>(true))
            {
                SoleContactCollisionObserver observer = owner.GetComponent<SoleContactCollisionObserver>();
                if (observer == null) observer = owner.gameObject.AddComponent<SoleContactCollisionObserver>();
                observer.Configure(this, owner);
            }

            writer.WriteLine(JsonUtility.ToJson(new SessionRow
            {
                utc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                articulationJoints = body.GetComponentsInChildren<FlyJoint>(true).Length,
                footPads = body.GetComponentsInChildren<FlyFootContact>(true).Length,
                endpoint = Endpoint(),
                mode = demo.mode.ToString()
            }));
            Debug.Log("SOLE_CONTACT_DIAGNOSTIC_START output=" + outputDirectory);
        }

        void ObserveTarget(FlyLeg leg, FlyLeg.LegDriveTarget target) => targets[leg] = target;

        void FixedUpdate()
        {
            if (writer == null || body == null || demo == null) return;
            ticks++;
            writer.WriteLine(JsonUtility.ToJson(new TickRow
            {
                utc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                tick = ticks,
                fixedTime = Time.fixedTime,
                articulationJoints = body.GetComponentsInChildren<FlyJoint>(true).Length,
                footPads = body.GetComponentsInChildren<FlyFootContact>(true).Length,
                bodyPosition = body.Position,
                bodyVelocity = body.LinearVelocity,
                phase = demo.controller == null ? 0f : demo.controller.EffectivePhase,
                legs = body.Legs.Where(leg => leg != null).Select(LegSnapshot).ToArray(),
                collisions = collisions.ToArray(),
                live = LiveSnapshot()
            }));
            collisions.Clear();
        }

        internal void ObserveCollision(ArticulationBody owner, Collision collision, string eventType)
        {
            if (writer == null || body == null || owner == null || collision == null) return;
            foreach (ContactPoint contact in collision.contacts)
            {
                bool ownerIsThis = contact.thisCollider != null && contact.thisCollider.attachedArticulationBody == owner;
                bool ownerIsOther = contact.otherCollider != null && contact.otherCollider.attachedArticulationBody == owner;
                if (!ownerIsThis && !ownerIsOther) continue;
                Collider own = ownerIsThis ? contact.thisCollider : contact.otherCollider;
                Collider other = ownerIsThis ? contact.otherCollider : contact.thisCollider;
                if (own == null || other == null || other.transform.IsChildOf(body.transform)) continue;

                FlyLeg leg;
                bool foot = feet.TryGetValue(own, out leg);
                if (foot) footCollisions++;
                else nonFootCollisions++;
                Vector3 normal = ownerIsThis ? contact.normal : -contact.normal;
                Vector3 impulse = contact.impulse;
                if (Vector3.Dot(impulse, normal) < 0f) impulse = -impulse;
                collisions.Add(new CollisionRow
                {
                    eventType = eventType,
                    observedFixedTime = Time.fixedTime,
                    classification = foot ? "FOOT" : "NON_FOOT",
                    leg = foot ? leg.LegId : string.Empty,
                    owner = owner.name,
                    ownCollider = own.name,
                    otherCollider = other.name,
                    point = contact.point,
                    normal = normal,
                    impulse = impulse,
                    relativeVelocity = collision.relativeVelocity
                });
            }
        }

        LegRow LegSnapshot(FlyLeg leg)
        {
            FlyFootContact contact = leg.FootContact;
            FlyFootAdhesion adhesion = leg.FootAdhesion;
            float phase = demo.controller == null ? 0f : demo.controller.EffectivePhase + (leg.Group == FlyLeg.TripodGroup.A ? 0f : Mathf.PI);
            Collider foot = contact == null ? null : contact.GetComponent<Collider>();
            Vector3 solePoint = soles.TryGetValue(leg, out var sole) ? sole.SurfacePoint : Vector3.zero;
            return new LegRow
            {
                leg = leg.LegId,
                commandStance = targets.TryGetValue(leg, out var target) ? target.stance : Mathf.Sin(phase) <= 0f,
                evaluatedStance = adhesion != null && adhesion.LastEvaluatedStance,
                attached = adhesion != null && adhesion.Attached,
                freshFootContact = contact != null && contact.HasFreshSurfaceContact,
                contactSource = contact == null ? "MISSING" : contact.ContactObservationSource,
                contactHoldTicks = contact == null ? 0 : contact.RemainingContactHoldTicks,
                otherCollider = contact == null ? string.Empty : contact.OtherColliderName,
                contactPoint = contact == null ? Vector3.zero : contact.SurfaceContactPoint,
                contactNormal = contact == null ? Vector3.zero : contact.SurfaceNormal,
                footColliderMinY = BoundsMinY(foot),
                femurCapsuleMinY = CapsuleMinY(leg.Femur),
                tibiaCapsuleMinY = CapsuleMinY(leg.Tibia),
                kneePosition = leg.Tibia.transform.position,
                footCenter = contact == null ? Vector3.zero : contact.transform.position,
                footBoundsExtents = foot == null ? Vector3.zero : foot.bounds.extents,
                visibleSole = solePoint,
                soleContactNormalError = contact != null && contact.HasFreshSurfaceContact && sole != null
                    ? Vector3.Dot(solePoint - contact.SurfaceContactPoint, contact.SurfaceNormal) : 0f,
                coxa = JointSnapshot(leg.Coxa, leg.LastCorrectedCoxaTarget),
                femur = JointSnapshot(leg.Femur, leg.LastCorrectedFemurTarget),
                tibia = JointSnapshot(leg.Tibia, leg.LastCorrectedTibiaTarget)
            };
        }

        LiveRow LiveSnapshot()
        {
            BrainFrame frame = null;
            double age = double.PositiveInfinity;
            if (demo.mode == WindowsReplayDemo.BrainSourceMode.LiveTcp)
            {
                if (demo.client != null) demo.client.TryGetLatestFrame(out frame, out age);
            }
            else if (demo.replay != null)
            {
                frame = demo.replay.LatestFrame;
                age = demo.replay.HasFreshFrame ? 0d : double.PositiveInfinity;
            }
            string protocolError = demo.client == null ? string.Empty : demo.client.LastError;
            if (!string.IsNullOrEmpty(protocolError) && protocolError != lastProtocolError)
            {
                observedProtocolErrors++;
                lastProtocolError = protocolError;
            }
            bool stale = demo.mode == WindowsReplayDemo.BrainSourceMode.LiveTcp
                ? demo.live == null || !demo.live.HasFreshFrame
                : demo.replay == null || !demo.replay.HasFreshFrame;
            return new LiveRow
            {
                endpoint = Endpoint(),
                connectionState = demo.client == null ? "MISSING" : demo.client.ConnectionState,
                backend = frame == null || frame.metadata == null ? string.Empty : frame.metadata.backendId,
                ready = frame != null && frame.metadata != null && frame.metadata.ready,
                sequence = frame == null ? -1 : frame.sequence,
                frameAgeSeconds = double.IsInfinity(age) ? -1f : (float)age,
                stale = stale,
                protocolError = protocolError,
                observedProtocolErrorCount = observedProtocolErrors,
                replayIndex = demo.replay == null ? -1 : demo.replay.CurrentFrameIndex,
                replayFrameCount = demo.replay == null ? 0 : demo.replay.FrameCount
            };
        }

        static JointRow JointSnapshot(FlyJoint joint, float appliedTarget)
        {
            ArticulationBody articulation = joint == null ? null : joint.Articulation;
            bool valid = articulation != null && articulation.jointPosition.dofCount > 0;
            return new JointRow
            {
                appliedTargetDegrees = appliedTarget,
                driveTargetDegrees = joint == null ? 0f : joint.Target,
                actualDegrees = valid ? articulation.jointPosition[0] * Mathf.Rad2Deg : 0f,
                velocityDegreesPerSecond = valid && articulation.jointVelocity.dofCount > 0 ? articulation.jointVelocity[0] * Mathf.Rad2Deg : 0f
            };
        }

        static float BoundsMinY(Collider collider) => collider == null ? -1f : collider.bounds.min.y;

        static float CapsuleMinY(FlyJoint joint)
        {
            if (joint == null) return -1f;
            CapsuleCollider[] capsules = joint.GetComponents<CapsuleCollider>();
            if (capsules.Length == 0) return -1f;
            float minY = float.PositiveInfinity;
            foreach (CapsuleCollider capsule in capsules) minY = Mathf.Min(minY, capsule.bounds.min.y);
            return minY;
        }

        string Endpoint()
        {
            return demo == null || demo.client == null ? string.Empty : demo.client.Host + ":" + demo.client.Port;
        }

        void OnDestroy()
        {
            if (closed) return;
            closed = true;
            if (demo != null && demo.controller != null) demo.controller.DiagnosticTargetObserved -= ObserveTarget;
            if (writer == null) return;
            string path = Path.Combine(outputDirectory, "sole-contact-summary.json");
            File.WriteAllText(path, JsonUtility.ToJson(new SummaryRow
            {
                utc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                tickCount = ticks,
                footCollisionCount = footCollisions,
                nonFootCollisionCount = nonFootCollisions,
                observedProtocolErrorCount = observedProtocolErrors,
                articulationJoints = body == null ? 0 : body.GetComponentsInChildren<FlyJoint>(true).Length,
                footPads = body == null ? 0 : body.GetComponentsInChildren<FlyFootContact>(true).Length
            }, true));
            writer.Dispose();
            Debug.Log("SOLE_CONTACT_DIAGNOSTIC_DONE ticks=" + ticks + " foot=" + footCollisions + " nonFoot=" + nonFootCollisions);
        }
    }

    public sealed class SoleContactCollisionObserver : MonoBehaviour
    {
        FlySoleContactDiagnostic diagnostic;
        ArticulationBody owner;

        internal void Configure(FlySoleContactDiagnostic nextDiagnostic, ArticulationBody nextOwner)
        {
            diagnostic = nextDiagnostic;
            owner = nextOwner;
        }

        void OnCollisionEnter(Collision collision) => diagnostic?.ObserveCollision(owner, collision, "ENTER");
        void OnCollisionStay(Collision collision) => diagnostic?.ObserveCollision(owner, collision, "STAY");
        void OnCollisionExit(Collision collision) => diagnostic?.ObserveCollision(owner, collision, "EXIT");
    }

    public sealed class SoleContactDiagnosticBootstrap : MonoBehaviour
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Boot()
        {
            if (!WindowsReplayDemo.Flag("-soleDiagnostic")) return;
            var root = new GameObject("Sole Contact Diagnostic Bootstrap");
            DontDestroyOnLoad(root);
            root.AddComponent<SoleContactDiagnosticBootstrap>();
        }

        System.Collections.IEnumerator Start()
        {
            yield return null;
            WindowsReplayDemo demo = FindFirstObjectByType<WindowsReplayDemo>(FindObjectsInactive.Include);
            if (demo == null) Debug.LogError("SOLE_CONTACT_DIAGNOSTIC could not find WindowsReplayDemo after scene load.");
            else if (demo.GetComponent<FlySoleContactDiagnostic>() == null) demo.gameObject.AddComponent<FlySoleContactDiagnostic>();
            Destroy(gameObject);
        }
    }
}
