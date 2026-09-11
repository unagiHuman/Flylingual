using System;
using UnityEngine;

namespace FlyLocomotionPoC
{
    [Serializable]
    public struct FlyMotorCommand
    {
        public float forward;
        public float turn;

        public FlyMotorCommand(float forward, float turn)
        {
            this.forward = Mathf.Clamp01(forward);
            this.turn = Mathf.Clamp(turn, -1f, 1f);
        }

        public static FlyMotorCommand Stop => new FlyMotorCommand(0f, 0f);
    }

    public abstract class FlyMotorSource : MonoBehaviour
    {
        public abstract FlyMotorCommand GetMotorCommand();

        public virtual string SourceName => GetType().Name;
    }
}
