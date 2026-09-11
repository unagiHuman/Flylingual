using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using FlyBrainPoC;
using UnityEngine;

namespace FlyLocomotionPoC
{
    public sealed class ReplayMotorSource : FlyMotorSource
    {
        private readonly List<BrainFrame> frames = new List<BrainFrame>();
        private int frameIndex;
        private float nextFrameTime;
        private bool configured;

        public BrainFrame LatestFrame { get; private set; }
        public bool HasFreshFrame { get; private set; }
        public int FrameCount => frames.Count;
        public int CurrentFrameIndex => frameIndex;
        public string ReplayPath { get; private set; } = string.Empty;

        public override string SourceName => "BrainFrameReplay";

        public void Configure(string path)
        {
            frames.Clear();
            frameIndex = 0;
            configured = false;
            ReplayPath = path ?? string.Empty;
            if (string.IsNullOrEmpty(ReplayPath) || !File.Exists(ReplayPath))
            {
                return;
            }

            foreach (string line in File.ReadLines(ReplayPath))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                try
                {
                    BrainFrame frame = JsonUtility.FromJson<BrainFrame>(line);
                    if (frame != null && frame.motor != null)
                    {
                        frames.Add(frame);
                    }
                }
                catch (Exception exception)
                {
                    Debug.LogWarning("Replay frame skipped: " + exception.Message);
                }
            }

            if (frames.Count == 0)
            {
                return;
            }

            LatestFrame = frames[0];
            HasFreshFrame = true;
            nextFrameTime = Time.unscaledTime + FrameDurationSeconds(LatestFrame);
            configured = true;
        }

        public override FlyMotorCommand GetMotorCommand()
        {
            if (!configured || frames.Count == 0)
            {
                HasFreshFrame = false;
                return FlyMotorCommand.Stop;
            }

            float now = Time.unscaledTime;
            while (frameIndex + 1 < frames.Count && now >= nextFrameTime)
            {
                frameIndex++;
                LatestFrame = frames[frameIndex];
                nextFrameTime += FrameDurationSeconds(LatestFrame);
            }

            if (frameIndex >= frames.Count - 1 && now >= nextFrameTime)
            {
                HasFreshFrame = false;
                return FlyMotorCommand.Stop;
            }

            HasFreshFrame = true;
            return new FlyMotorCommand(LatestFrame.motor.forward, LatestFrame.motor.turn);
        }

        private static float FrameDurationSeconds(BrainFrame frame)
        {
            float milliseconds = frame == null || frame.performance == null
                ? 180f
                : frame.performance.stepWallTimeMs;
            return Mathf.Max(0.02f, milliseconds / 1000f);
        }
    }
}
