using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using FlyLocomotionPoC;
using FlyVisualDemo;
using UnityEngine;

namespace Flylingual.Conversation
{
    /// <summary>Opt-in real text/Brain/body distance acceptance. Never supplies motor or positions.</summary>
    public sealed class DistanceIntentProbe : MonoBehaviour
    {
        [Serializable] sealed class Event
        {
            public string type, stage, reason, action, executionId;
            public int epoch;
            public bool completed;
            public float targetDistanceMeters, traveledMeters, remainingMeters;
        }
        [Serializable] sealed class Sample
        {
            public float time, forward, turn, travel, remaining, horizontalSpeed;
            public double odometer;
            public long sequence;
            public Vector3 position;
            public string mode;
        }
        [Serializable] sealed class Trial
        {
            public string text, result, reason;
            public float requestedMeters, reportedMeters, horizontalDisplacement, measuredTravelMeters, distanceErrorMeters;
            public bool acceptedDistance, completed, stopped, listening, stopSent, distanceWithinTolerance;
            public List<Sample> samples = new List<Sample>();
        }
        [Serializable] sealed class Report
        {
            public string endpoint = "127.0.0.1:18766", backend, mode, result, error;
            public bool ready;
            public List<Trial> trials = new List<Trial>();
        }
        ConversationSessionController conversation;
        WindowsReplayDemo demo;
        Event finished;
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            if (!string.IsNullOrEmpty(WindowsReplayDemo.Argument("-distanceProbe")))
                new GameObject("Distance Intent Acceptance").AddComponent<DistanceIntentProbe>();
        }
        IEnumerator Start()
        {
            string directory = Path.GetFullPath(WindowsReplayDemo.Argument("-distanceProbe"));
            Directory.CreateDirectory(directory);
            var report = new Report();
            float deadline = Time.realtimeSinceStartup + 65;
            while (Time.realtimeSinceStartup < deadline)
            {
                conversation = FindFirstObjectByType<ConversationSessionController>();
                demo = FindFirstObjectByType<WindowsReplayDemo>();
                if (conversation != null && conversation.Ready && conversation.BodyControlActive && demo?.body != null
                    && demo.body.GetComponent<FlyTerrainRuntime>()?.TravelMeters >= 0) break;
                yield return new WaitForSecondsRealtime(.2f);
            }
            if (conversation == null || !conversation.BodyControlActive || demo?.body == null)
                report.error = "startup_not_ready";
            else
            {
                conversation.ControlEventReceived += OnEvent;
                float target = WindowsReplayDemo.Flag("-distanceProbeShort") ? .5f : 5f;
                var distance = new Trial { text = target == 5f ? "5mぐらい前に進んで" : "半メートルぐらい前に進んで", requestedMeters = target };
                report.trials.Add(distance); yield return RunTrial(distance, false);
                if (distance.acceptedDistance && distance.stopped && distance.listening)
                {
                    var vague = new Trial { text = "ちょっと前へ", requestedMeters = .5f };
                    report.trials.Add(vague); yield return RunTrial(vague, false);
                    if (vague.acceptedDistance && vague.stopped && vague.listening)
                    {
                        var stop = new Trial { text = "5mぐらい前に進んで", requestedMeters = 5f };
                        report.trials.Add(stop); yield return RunTrial(stop, true);
                    }
                }
                conversation.ControlEventReceived -= OnEvent;
                var frame = demo.live?.LatestFrame;
                report.backend = frame?.metadata?.backendId; report.mode = frame?.metadata?.mode; report.ready = frame != null && frame.metadata.ready;
            }
            report.result = report.trials.Count == 3 && report.trials.TrueForAll(t => t.result == "pass") ? "pass" : "incomplete";
            File.WriteAllText(Path.Combine(directory, "report.json"), JsonUtility.ToJson(report, true));
            ScreenCapture.CaptureScreenshot(Path.Combine(directory, "screen.png"));
            yield return new WaitForSecondsRealtime(.3f);
            Application.Quit();
        }
        void OnEvent(string json)
        {
            var item = JsonUtility.FromJson<Event>(json);
            if (item?.type == "command_result" && (item.stage == "execution_finished" || item.stage == "rejected")) finished = item;
        }
        IEnumerator RunTrial(Trial trial, bool interrupt)
        {
            finished = null;
            var odometer = demo.body.GetComponent<FlyTerrainRuntime>();
            Vector3 origin = demo.body.Position;
            double travelOrigin = odometer.TravelMeters;
            conversation.SendPlayerText(trial.text);
            float deadline = Time.realtimeSinceStartup + 100;
            float admissionDeadline = Time.realtimeSinceStartup + 15;
            bool sawActive = false;
            while (Time.realtimeSinceStartup < deadline)
            {
                var execution = conversation.ActiveExecution;
                var motor = demo.controller.CurrentMotor;
                var frame = demo.live?.LatestFrame;
                trial.samples.Add(new Sample { time = Time.realtimeSinceStartup, forward = motor.forward, turn = motor.turn,
                    sequence = frame?.sequence ?? -1, odometer = odometer == null ? -1 : odometer.TravelMeters,
                    travel = execution?.traveledMeters ?? 0, remaining = execution?.remainingMeters ?? 0,
                    mode = execution?.executionMode, position = demo.body.Position, horizontalSpeed = odometer.HorizontalSpeedMetersPerSecond });
                if (execution?.executionMode == "distance")
                {
                    sawActive = trial.acceptedDistance = true;
                    trial.reportedMeters = Mathf.Max(trial.reportedMeters, execution.traveledMeters);
                    if (Mathf.Abs(execution.targetDistanceMeters - trial.requestedMeters) > .001f)
                    { trial.reason = "wrong_distance_interpretation"; break; }
                    if (interrupt && !trial.stopSent && execution.traveledMeters > .2f)
                    { conversation.SendPlayerText("止まって"); trial.stopSent = true; }
                }
                if (finished != null)
                {
                    trial.reason = finished.reason; trial.completed = finished.completed;
                    trial.reportedMeters = finished.traveledMeters; break;
                }
                if (sawActive && execution == null)
                {
                    trial.reason = trial.stopSent ? "explicit_stop" : "execution_disappeared"; break;
                }
                if (!conversation.BodyControlActive) { trial.reason = "body_control_lost"; break; }
                if (!sawActive && Time.realtimeSinceStartup >= admissionDeadline) { trial.reason = "distance_not_accepted"; break; }
                yield return new WaitForSecondsRealtime(.1f);
            }
            if (string.IsNullOrEmpty(trial.reason)) trial.reason = "trial_timeout";
            // Observe the ordinary STOP settling; this does not override the body.
            float settle = Time.realtimeSinceStartup + 8;
            float stableSince = -1;
            while (Time.realtimeSinceStartup < settle)
            {
                var frame = demo.live?.LatestFrame;
                var motor = demo.controller.CurrentMotor;
                trial.samples.Add(new Sample { time = Time.realtimeSinceStartup, forward = motor.forward, turn = motor.turn,
                    sequence = frame?.sequence ?? -1, odometer = odometer.TravelMeters,
                    position = demo.body.Position, horizontalSpeed = odometer.HorizontalSpeedMetersPerSecond });
                if (conversation.ActiveExecution == null && frame?.requestedAction == "STOP"
                    && Mathf.Abs(motor.forward) < .02f && Mathf.Abs(motor.turn) < .02f && odometer.HorizontalSpeedMetersPerSecond < .03f)
                {
                    if (stableSince < 0) stableSince = Time.realtimeSinceStartup;
                    if (Time.realtimeSinceStartup - stableSince >= .5f) { trial.stopped = true; break; }
                }
                else stableSince = -1;
                yield return new WaitForSecondsRealtime(.1f);
            }
            trial.listening = conversation.BodyControlActive && conversation.ConversationLive;
            trial.horizontalDisplacement = Vector3.ProjectOnPlane(demo.body.Position - origin, Vector3.up).magnitude;
            trial.measuredTravelMeters = (float)(odometer.TravelMeters - travelOrigin);
            trial.distanceErrorMeters = trial.measuredTravelMeters - trial.requestedMeters;
            trial.distanceWithinTolerance = Mathf.Abs(trial.distanceErrorMeters) <= Mathf.Min(.5f, Mathf.Max(.15f, trial.requestedMeters * .1f));
            trial.result = trial.acceptedDistance && trial.stopped && trial.listening
                && (interrupt ? trial.stopSent && !trial.completed
                    : trial.measuredTravelMeters >= trial.requestedMeters * .5f
                        && (trial.reason == "distance_reached" || trial.reason == "distance_overshoot" || trial.reason == "distance_shortfall"))
                ? "pass" : "incomplete";
            if (!trial.stopped && conversation.BodyControlActive) conversation.SendPlayerText("止まって");
            yield return new WaitForSecondsRealtime(.5f);
        }
    }
}
