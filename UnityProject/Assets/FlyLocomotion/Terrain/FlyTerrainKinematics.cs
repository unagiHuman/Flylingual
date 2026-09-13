using UnityEngine;

namespace FlyLocomotionPoC
{
    // Virtual forward kinematics; only FlyLeg.ApplyDriveTargets writes articulation drives.
    internal sealed class FlyTerrainKinematics
    {
        readonly Vector3[] pivots = new Vector3[3], axes = new Vector3[3];
        readonly FlyJoint[] joints = new FlyJoint[3];
        public Vector3 Endpoint(FlyLeg leg, Vector3 angles)
        {
            joints[0] = leg.Coxa; joints[1] = leg.Femur; joints[2] = leg.Tibia;
            Vector3 tip = leg.FootProbePosition;
            for (int i = 0; i < 3; i++)
            {
                var a = joints[i].Articulation;
                pivots[i] = a.transform.TransformPoint(a.anchorPosition);
                axes[i] = a.transform.TransformDirection(a.anchorRotation * Vector3.right).normalized;
            }
            for (int i = 0; i < 3; i++)
            {
                var a = joints[i].Articulation;
                float actual = a.jointPosition.dofCount > 0 ? a.jointPosition[0] * Mathf.Rad2Deg : 0f;
                var rotation = Quaternion.AngleAxis(angles[i] - actual, axes[i]);
                tip = pivots[i] + rotation * (tip - pivots[i]);
                for (int j = i + 1; j < 3; j++)
                { pivots[j] = pivots[i] + rotation * (pivots[j] - pivots[i]); axes[j] = rotation * axes[j]; }
            }
            return tip;
        }
        public Vector3 Solve(FlyLeg leg, Vector3 nominal, Vector3 goal, float maxCorrection)
        {
            Vector3 result = nominal;
            for (int pass = 0; pass < 6; pass++)
                for (int i = 2; i >= 0; i--)
                {
                    Vector3 tip = Endpoint(leg, result);
                    Vector3 a = Vector3.ProjectOnPlane(tip - pivots[i], axes[i]);
                    Vector3 b = Vector3.ProjectOnPlane(goal - pivots[i], axes[i]);
                    if (a.sqrMagnitude < .000001f || b.sqrMagnitude < .000001f) continue;
                    float delta = Vector3.SignedAngle(a, b, axes[i]);
                    var drive = joints[i].Articulation.xDrive;
                    float min = Mathf.Max(drive.lowerLimit, nominal[i] - maxCorrection);
                    float max = Mathf.Min(drive.upperLimit, nominal[i] + maxCorrection);
                    result[i] = Mathf.Clamp(result[i] + Mathf.Clamp(delta, -8f, 8f), min, max);
                }
            return result;
        }
    }
}
