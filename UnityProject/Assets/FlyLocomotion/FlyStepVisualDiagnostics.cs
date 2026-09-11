using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class FlyStepVisualDiagnostics : MonoBehaviour
    {
        [SerializeField] private FlyBody flyBody;
        [SerializeField] private FlyLocomotionController controller;
        [SerializeField] private FlyStepObstacle obstacle;
        [SerializeField] private FlyLocalReflexLayer reflexLayer;
        [SerializeField] private bool drawGizmos = true;
        [SerializeField] private bool showOnGUI = true;
        [SerializeField] private int trajectoryCapacity = 240;
        [SerializeField] private float probeRadius = 0.15f;

        private readonly Collider[] probeHits = new Collider[16];
        private readonly List<Vector3> trajectory = new List<Vector3>();
        private readonly Dictionary<string, Vector3> previousFootPositions = new Dictionary<string, Vector3>();
        private readonly Dictionary<string, Vector3> footVelocities = new Dictionary<string, Vector3>();

        public void Configure(FlyBody body, FlyLocomotionController locomotionController, FlyStepObstacle step, FlyLocalReflexLayer reflex)
        {
            flyBody = body;
            controller = locomotionController;
            obstacle = step;
            reflexLayer = reflex;
        }

        private void FixedUpdate()
        {
            if (flyBody == null)
            {
                return;
            }

            trajectory.Add(flyBody.Position);
            int excess = trajectory.Count - Mathf.Max(2, trajectoryCapacity);
            if (excess > 0)
            {
                trajectory.RemoveRange(0, excess);
            }

            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyLeg leg = flyBody.Legs[i];
                if (leg == null) continue;
                Vector3 foot = leg.FootProbePosition;
                if (previousFootPositions.TryGetValue(leg.LegId, out Vector3 previous))
                {
                    footVelocities[leg.LegId] = (foot - previous) / Mathf.Max(0.0001f, Time.fixedDeltaTime);
                }
                previousFootPositions[leg.LegId] = foot;
            }
        }

        private void OnDrawGizmos()
        {
            if (!drawGizmos || flyBody == null)
            {
                return;
            }

            Gizmos.color = new Color(0.25f, 0.75f, 1f, 0.85f);
            for (int i = 1; i < trajectory.Count; i++)
            {
                Gizmos.DrawLine(trajectory[i - 1], trajectory[i]);
            }

            if (obstacle != null)
            {
                Gizmos.color = Color.cyan;
                Vector3 center = new Vector3(
                    (obstacle.TopSurfaceStartX + obstacle.TopSurfaceEndX) * 0.5f,
                    obstacle.ObstacleHeight,
                    0f);
                Vector3 size = new Vector3(
                    obstacle.TopSurfaceEndX - obstacle.TopSurfaceStartX,
                    0.01f,
                    obstacle.UpperPlatformHalfWidth * 2f);
                Gizmos.DrawWireCube(center, size);
            }

            IReadOnlyList<FlyLeg> legs = flyBody.Legs;
            for (int i = 0; i < legs.Count; i++)
            {
                FlyLeg leg = legs[i];
                if (leg == null)
                {
                    continue;
                }

                Vector3 probe = leg.FootProbePosition;
                string surface = GetSurface(probe, out Vector3 contactPoint);
                Gizmos.color = surface == "TOP" ? Color.yellow
                    : surface == "FRONT" ? Color.red
                    : surface == "GROUND" ? Color.green
                    : Color.white;
                Gizmos.DrawSphere(probe, 0.035f);
                Gizmos.DrawLine(probe, probe + Vector3.up * 0.12f);
                if (footVelocities.TryGetValue(leg.LegId, out Vector3 velocity))
                {
                    Gizmos.color = Color.magenta;
                    Gizmos.DrawLine(probe, probe + velocity * 0.2f);
                }
                if (obstacle != null && obstacle.TryGetLegContactSnapshot(leg.LegId, out FlyStepObstacle.LegContactSnapshot snapshot) && snapshot.top)
                {
                    Gizmos.color = Color.blue;
                    Gizmos.DrawSphere(snapshot.point, 0.045f);
                    Gizmos.DrawLine(snapshot.point, snapshot.point + snapshot.normal * 0.25f);
                }
                if (surface != "NONE")
                {
                    Gizmos.DrawWireSphere(contactPoint, 0.045f);
                }
            }
        }

        private void OnGUI()
        {
            if (!showOnGUI || flyBody == null || controller == null)
            {
                return;
            }

            GUILayout.BeginArea(new Rect(12f, Screen.height - 280f, 470f, 268f), GUI.skin.box);
            GUILayout.Label("Step diagnostics");
            GUILayout.Label("Phase=" + Format(controller.Phase * Mathf.Rad2Deg) + " deg effective=" + Format(controller.EffectivePhase * Mathf.Rad2Deg) + "  Thorax=" + FormatVector(flyBody.Position));
            GUILayout.Label("Velocity=" + FormatVector(flyBody.LinearVelocity) + "  Ground=" + flyBody.GroundContactCount + "/6");
            if (reflexLayer != null)
            {
                GUILayout.Label("Reflex raw/effective=" + Format(reflexLayer.RawForward) + "/" + Format(reflexLayer.EffectiveForward) +
                                 " phaseEscape=" + reflexLayer.PhaseEscapeActive + " rearStep=" + reflexLayer.RearStepUpActive);
                GUILayout.Label("Reflex A/B=" + reflexLayer.PhaseEscapeActivationCount + "/" + reflexLayer.RearStepUpActivationCount +
                                 " state=" + reflexLayer.RearStepUpStateName + " leg=" + reflexLayer.ActiveRearLegId);
                GUILayout.Label("Rear offsets=" + Format(reflexLayer.RearStepUpCoxaOffsetAppliedDegrees) + "/" +
                                 Format(reflexLayer.RearStepUpFemurOffsetAppliedDegrees) + "/" +
                                 Format(reflexLayer.RearStepUpTibiaOffsetAppliedDegrees) +
                                 " rearTop=" + reflexLayer.RearSupportPresent);
                GUILayout.Label("Rear propulsion=" + reflexLayer.RearPropulsionActive +
                                 " coxaMultiplier=" + Format(reflexLayer.RearStanceCoxaMultiplier));
            }
            for (int i = 0; i < flyBody.Legs.Count; i++)
            {
                FlyLeg leg = flyBody.Legs[i];
                if (leg == null)
                {
                    continue;
                }

                Vector3 probe = leg.FootProbePosition;
                string surface = GetSurface(probe, out _);
                GUILayout.Label(leg.LegId + " foot=" + FormatVector(probe) + " surface=" + surface + " grounded=" + leg.IsGrounded);
            }

            GUILayout.EndArea();
        }

        private string GetSurface(Vector3 probe, out Vector3 contactPoint)
        {
            contactPoint = probe;
            int hitCount = Physics.OverlapSphereNonAlloc(probe, probeRadius, probeHits, ~0, QueryTriggerInteraction.Ignore);
            for (int i = 0; i < hitCount; i++)
            {
                Collider collider = probeHits[i];
                if (collider == null)
                {
                    continue;
                }

                if (collider.GetComponentInParent<FlyStepObstacle>() is FlyStepObstacle step)
                {
                    contactPoint = collider.ClosestPoint(probe);
                    return step.ClassifyContactPoint(contactPoint);
                }

                if (collider.GetComponentInParent<FlyGroundMarker>() != null)
                {
                    contactPoint = collider.ClosestPoint(probe);
                    return "GROUND";
                }
            }

            return "NONE";
        }

        private static string Format(float value)
        {
            return value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        private static string FormatVector(Vector3 value)
        {
            return "(" + Format(value.x) + "," + Format(value.y) + "," + Format(value.z) + ")";
        }
    }
}
