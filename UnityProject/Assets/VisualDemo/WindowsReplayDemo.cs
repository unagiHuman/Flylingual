using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using FlyBrainPoC;
using FlyLocomotionPoC;
using UnityEngine;
using Flylingual.PlayScreen;

namespace FlyVisualDemo
{
    [DefaultExecutionOrder(-200)]
    public sealed class WindowsReplayDemo : MonoBehaviour
    {
        public enum BrainSourceMode { Replay, LiveTcp }
        public BrainSourceMode mode;
        public FlyBody body;
        public FlyLocomotionController controller;
        public ReplayMotorSource replay;
        public BrainMotorSource live;
        public BrainTcpClient client;
        public Transform visualRig;
        public Camera view;
        public FlyGameplayPreset gameplayPreset;
        public string fixtureName = "shiu_game_brain_controller_frames_wire_v1.jsonl";
        public bool loop;
        readonly string[] actions = { "STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L" };
        string[] originalLines;
        string[] selectedLines;
        string selected = "ALL";
        string error;
        string output;
        StreamWriter samples;
        Vector3 origin;
        int lastIndex = -1;
        double frameAt;
        float quitAfter;
        bool captured;
        bool emergency;
        float startedAt;
        float nextConnectAttempt;
        BrainFrame previousLiveFrame;
        bool waitingForLiveFrame;
        int skippedFrames;
        int observedFrames;
        int jointCount,footCount,visualPhysicsCount;
        VisualRigMapper mapper;
        AscentGameSession game;
        static bool controlsRestarted;
        int controlStep;
        Vector3 pausedPosition;
        float nextVideoFrame;
        int videoFrame;
        bool playbackStarting;
        bool delayingLiveConnection;
        string reportedLiveConnectionState;
        string reportedLiveError;
        bool browserControlled;
        int warmupFrames;
        readonly List<float> renderTimes = new List<float>();
        GUIStyle titleStyle, textStyle, smallStyle, buttonStyle;
        public static string Argument(string key)
        {
            var a = Environment.GetCommandLineArgs(); int i = Array.IndexOf(a, key);
            return i >= 0 && i + 1 < a.Length ? a[i + 1] : "";
        }
        public static bool Flag(string key) => Array.IndexOf(Environment.GetCommandLineArgs(), key) >= 0;
        void Awake()
        {
            Application.targetFrameRate = 60;
            Application.runInBackground = true;
            startedAt = Time.realtimeSinceStartup;
            game = GetComponent<AscentGameSession>();
            browserControlled = Flag("-demoBrowserControlled");
            if (browserControlled)
            {
                client.EnableReceiveOnly();
                if (game != null) game.enabled = false;
            }
            if(Flag("-demoLoop")) loop=true;
            client.enabled = false;
            client.Disconnect();
            origin = body.Position;
            jointCount=body.GetComponentsInChildren<ArticulationBody>().Length-1;
            footCount=body.GetComponentsInChildren<FlyFootContact>().Length;
            visualPhysicsCount=visualRig==null?0:visualRig.GetComponentsInChildren<Collider>(true).Length+visualRig.GetComponentsInChildren<Rigidbody>(true).Length+visualRig.GetComponentsInChildren<ArticulationBody>(true).Length;
            mapper=visualRig==null?null:visualRig.GetComponent<VisualRigMapper>();
            if(gameplayPreset!=null && string.IsNullOrEmpty(Argument("-steeringTrial"))) gameplayPreset.Apply(this);
            output = Argument("-demoOutput");
            if (string.IsNullOrEmpty(output)) output = Path.Combine(Application.persistentDataPath, "WindowsReplay");
            Directory.CreateDirectory(output);
            samples = new StreamWriter(Path.Combine(output, (browserControlled ? "browser_body_samples_" : "replay_samples_") + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + ".csv"));
            samples.WriteLine("time,mode,index,sequence,action,forward,turn,DNp09,DNa02_R,DNa02_L,dx,dy,dz,yaw,attached,grip,detach");
            samples.AutoFlush = true;
            float.TryParse(Argument("-demoQuitAfter"), NumberStyles.Float, CultureInfo.InvariantCulture, out quitAfter);
            // Native conversation starts with no motor route. It never loads a
            // recorded source and cannot reconnect / resume the body implicitly.
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled)
            {
                mode = BrainSourceMode.LiveTcp;
                if (game != null) game.enabled = false;
                if (view != null) view.rect = new Rect(0, 0, 1, 1);
                Time.timeScale = 0;
                controller.SetMotorSource(null);
                emergency = true;
                return;
            }
            if (browserControlled)
            {
                if (!ConfigureBrowserControl()) return;
            }
            else
            {
                try
                {
                    string path = Path.Combine(Application.streamingAssetsPath, fixtureName);
                    if (!string.IsNullOrEmpty(Argument("-demoReplay"))) path = Path.GetFullPath(Argument("-demoReplay"));
                    originalLines = File.ReadAllLines(path).Where(s => !string.IsNullOrWhiteSpace(s)).ToArray();
                    if (originalLines.Length == 0) throw new InvalidDataException("Replay is empty");
                    foreach (string line in originalLines)
                        foreach (string key in new[] { "sequence", "forward", "turn" })
                            if (!Regex.IsMatch(line, "\"" + key + "\"\\s*:\\s*-?[0-9]")) throw new InvalidDataException("Replay missing numeric " + key);
                    SelectReplay(string.IsNullOrEmpty(Argument("-demoAction")) ? "ALL" : Argument("-demoAction"));
                }
                catch (Exception e) { error = e.Message; Debug.LogError("REPLAY_LOAD_FAILED " + e); controller.SetMotorSource(null); }
            }
            if (Flag("-demoHideVisual") && visualRig != null) foreach (var r in visualRig.GetComponentsInChildren<Renderer>()) r.enabled = false;
            if (browserControlled || Flag("-demoLive"))
            {
                string host=Argument("-brainHost");
                if(!browserControlled && !string.IsNullOrEmpty(host)) client.ConfigureEndpoint(host,int.Parse(Argument("-brainPort"),CultureInfo.InvariantCulture),false);
                float.TryParse(Argument("-demoLiveConnectDelay"), NumberStyles.Float, CultureInfo.InvariantCulture, out float delay);
                if (browserControlled || delay > 0f)
                {
                    // Allow local Brain/Bridge startup to remain inhibited
                    // during Player loading. No replay motor runs in this gap.
                    mode = BrainSourceMode.LiveTcp;
                    delayingLiveConnection = true;
                    controller.SetMotorSource(null);
                    float delaySeconds = browserControlled ? Mathf.Clamp(delay, .05f, 30f) : Mathf.Min(delay, 30f);
                    Debug.Log("LIVE_TCP_DELAY_REALTIME seconds=" + delaySeconds.ToString("R", CultureInfo.InvariantCulture) + " endpoint=" + client.Host + ":" + client.Port);
                    // AfterSceneLoad publishers must subscribe to ReceivedLine before
                    // the Bridge sends its initial identity status on connection.
                    // The session intro intentionally pauses scaled game time.  Live
                    // transport startup must remain a realtime wait so the paused
                    // safe-stop state cannot prevent a requested TCP connection.
                    StartCoroutine(StartLiveConnectionAfterDelay(delaySeconds));
                }
                else StartLiveConnection();
            }
            playbackStarting = Flag("-demoWarmup") && mode == BrainSourceMode.Replay;
            if (playbackStarting) controller.SetMotorSource(null);
        }
        bool ConfigureBrowserControl()
        {
            mode = BrainSourceMode.LiveTcp;
            controller.SetMotorSource(null);
            replay.enabled = false;
            loop = false;
            foreach (string flag in new[] { "-liveTrial", "-demoExerciseControls", "-steeringTrial", "-physicsDiagnostic", "-demoReplay", "-demoAction", "-demoLoop", "-demoWarmup" })
                if (Flag(flag)) return RejectBrowserControl("incompatible option " + flag);
            string host = Argument("-brainHost");
            if ((host != "127.0.0.1" && host != "localhost" && host != "::1") ||
                !int.TryParse(Argument("-brainPort"), NumberStyles.None, CultureInfo.InvariantCulture, out int port) || port < 1 || port > 65535)
                return RejectBrowserControl("explicit loopback -brainHost and Bridge -brainPort are required");
            string delayText = Argument("-demoLiveConnectDelay");
            if (delayText.Length > 0 && (!float.TryParse(delayText, NumberStyles.Float, CultureInfo.InvariantCulture, out float delay) ||
                float.IsNaN(delay) || float.IsInfinity(delay) || delay < 0f))
                return RejectBrowserControl("invalid -demoLiveConnectDelay");
            client.ConfigureEndpoint(host, port, false);
            live.enabled = true;
            client.enabled = true;
            Debug.Log("BROWSER_BODY_CONFIGURED receiveOnly=true source=LIVE endpoint=" + host + ":" + port);
            return true;
        }
        bool RejectBrowserControl(string reason)
        {
            error = reason;
            controller.SetMotorSource(null);
            controller.enabled = false;
            client.Disconnect();
            enabled = false;
            Time.timeScale = 0f;
            Debug.LogError("BROWSER_BODY_CONFIG_INVALID " + reason);
            Application.Quit(2);
            return false;
        }
        void StartLiveConnection()
        {
            delayingLiveConnection = false;
            Debug.Log("LIVE_TCP_START endpoint=" + client.Host + ":" + client.Port);
            if(Flag("-liveTrial")) gameObject.AddComponent<LiveIntegrationTrial>();
            SetMode(BrainSourceMode.LiveTcp);
        }
        IEnumerator StartLiveConnectionAfterDelay(float seconds)
        {
            yield return new WaitForSecondsRealtime(seconds);
            StartLiveConnection();
        }
        public void SelectReplay(string action)
        {
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled || browserControlled) return;
            if (originalLines == null) return;
            selectedLines = action == "ALL" ? originalLines : originalLines.Where(s => JsonUtility.FromJson<BrainFrame>(s).requestedAction == action).ToArray();
            if (selectedLines.Length == 0) { error = "No recorded frames for " + action; return; }
            string path = Path.Combine(output, "selected_replay.jsonl");
            File.WriteAllLines(path, selectedLines);
            replay.Configure(path); selected = action; lastIndex = -1; frameAt = Time.realtimeSinceStartupAsDouble; emergency = false;
            Time.timeScale=1;
            controller.SetMotorSource(replay); mode = BrainSourceMode.Replay; client.Disconnect(); client.enabled = false;
        }
        void SetMode(BrainSourceMode next)
        {
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled ||
                (browserControlled && next != BrainSourceMode.LiveTcp)) return;
            emergency = false; mode = next; lastIndex = -1; Time.timeScale=1;
            if (next == BrainSourceMode.Replay) SelectReplay(selected);
            else { previousLiveFrame=client.LatestBrainFrame; waitingForLiveFrame=true; client.enabled = true; client.Connect(); controller.SetMotorSource(null); }
        }
        // Leaves the local intro pause while retaining the selected LiveTcp transport.
        // A motor source is installed only after a frame newer than this boundary arrives.
        public void BeginLiveSession()
        {
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled) return;
            if (mode != BrainSourceMode.LiveTcp) return;
            emergency = false;
            Time.timeScale = 1;
            previousLiveFrame = client.LatestBrainFrame;
            waitingForLiveFrame = true;
            controller.SetMotorSource(null);
        }
        void Update()
        {
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled)
            {
                // NativeConversationBody lives on the conversation bootstrap object,
                // not necessarily this demo object.  It is the sole owner of the
                // live source while the native safety gate is armed; clearing it
                // here would overwrite its validated SetMotorSource(demo.live).
                if (quitAfter > 0 && Time.realtimeSinceStartup-startedAt >= quitAfter) Application.Quit();
                return;
            }
            // Optional benchmark warmup keeps loading/render startup out of recorded playback.
            // The fixture, frame durations and motor values are unchanged.
            if (playbackStarting && ++warmupFrames >= 60)
            { playbackStarting=false; SelectReplay(selected); Debug.Log("REPLAY_WARMUP_COMPLETE"); }
            renderTimes.Add(Time.unscaledDeltaTime*1000f);
            if (mode == BrainSourceMode.Replay && loop && !emergency && replay.FrameCount > 0 && !replay.HasFreshFrame) SelectReplay(selected);
            // Disconnect cancels asynchronously; retry after its old task has exited.
            if (!delayingLiveConnection && !Flag("-liveTrial") && mode == BrainSourceMode.LiveTcp && client.ConnectionState == "DISCONNECTED" && Time.unscaledTime >= nextConnectAttempt)
            { nextConnectAttempt=Time.unscaledTime+.5f; client.Connect(); }
            if(mode==BrainSourceMode.LiveTcp)
            {
                if(client.ConnectionState!="CONNECTED") { previousLiveFrame=client.LatestBrainFrame; waitingForLiveFrame=true; controller.SetMotorSource(null); }
                else if(waitingForLiveFrame && client.LatestBrainFrame!=null && !ReferenceEquals(previousLiveFrame,client.LatestBrainFrame))
                { waitingForLiveFrame=false; if(!emergency) controller.SetMotorSource(live); }
                ReportLiveConnection();
            }
            if (quitAfter > 0 && Time.realtimeSinceStartup-startedAt >= quitAfter) Application.Quit();
            if(Flag("-demoExerciseControls") && !controlsRestarted)
            {
                float elapsed=Time.realtimeSinceStartup-startedAt;
                if(controlStep==0 && elapsed>2) {PauseDemo();pausedPosition=body.Position;controlStep=1;}
                else if(controlStep==1 && elapsed>3) {Debug.Log("CONTROL_PAUSE_DRIFT "+Vector3.Distance(pausedPosition,body.Position).ToString("R",CultureInfo.InvariantCulture));SelectReplay("FORWARD");controlStep=2;}
                else if(controlStep==2 && elapsed>7) {controlsRestarted=true;Debug.Log("CONTROL_RESTART_REQUESTED");RestartDemo();}
            }
        }
        void ReportLiveConnection()
        {
            string state = client.ConnectionState;
            string last = client.LastError ?? string.Empty;
            if (state == reportedLiveConnectionState && last == reportedLiveError) return;
            reportedLiveConnectionState = state;
            reportedLiveError = last;
            Debug.Log("LIVE_TCP_STATE state=" + state + " endpoint=" + client.Host + ":" + client.Port +
                " lastError=" + (string.IsNullOrEmpty(last) ? "none" : last));
        }
        void LateUpdate()
        {
            if (view != null)
            {
                Vector3 offset = new Vector3(7, 5.5f, 8);
                switch (Argument("-demoView")) { case "front": offset = new Vector3(0, 2, 10); break; case "side": offset = new Vector3(10, 2, 0); break; case "top": offset = new Vector3(.01f, 12, 0); break; }
                if(game!=null && game.enabled) offset=Quaternion.Euler(0,game.Orbit,0)*(gameplayPreset==null?new Vector3(7,7,-10):gameplayPreset.cameraOffset)*game.Zoom;
                view.transform.position = body.Position + offset;
                view.transform.LookAt(body.Position + Vector3.up * .2f + (game!=null && game.enabled?Vector3.forward*(gameplayPreset==null?2:gameplayPreset.cameraLookAhead):Vector3.zero));
            }
            BrainFrame f = mode == BrainSourceMode.Replay ? replay.LatestFrame : client.LatestBrainFrame;
            int index = mode == BrainSourceMode.Replay ? replay.CurrentFrameIndex : f == null ? -1 : f.sequence;
            if (!playbackStarting && f != null && index != lastIndex)
            {
                if(mode==BrainSourceMode.Replay && lastIndex>=0 && index>lastIndex+1) { skippedFrames+=index-lastIndex-1; Debug.LogWarning("REPLAY_SAMPLE_GAP skipped="+(index-lastIndex-1)); }
                frameAt = Time.realtimeSinceStartupAsDouble; lastIndex = index;
                observedFrames++;
                Grip(out int attached, out float utilization, out int detach);
                Vector3 d = body.Position - origin;
                samples.WriteLine(string.Join(",", new[] { N(Time.realtimeSinceStartup), mode.ToString(), index.ToString(), f.sequence.ToString(), f.requestedAction,
                    N(f.motor.forward), N(f.motor.turn), Raw("DNp09_Hz", f.brain?.DNp09_Hz), Raw("DNa02_R_Hz", f.brain?.DNa02_R_Hz), Raw("DNa02_L_Hz", f.brain?.DNa02_L_Hz),
                    N(d.x), N(d.y), N(d.z), N(body.Thorax.transform.eulerAngles.y), attached.ToString(), N(utilization), detach.ToString() }));
            }
            if (!captured && Time.realtimeSinceStartup-startedAt > 3 && Flag("-demoCapture"))
            { captured = true; ScreenCapture.CaptureScreenshot(Path.Combine(output, "demo.png")); }
            if(Flag("-demoRecord") && Time.realtimeSinceStartup-startedAt>=nextVideoFrame && videoFrame<90)
            {
                nextVideoFrame=Time.realtimeSinceStartup-startedAt+1f/15;
                ScreenCapture.CaptureScreenshot(Path.Combine(output,"frame_"+(videoFrame++).ToString("D4")+".png"));
            }
        }
        string Raw(string key, float? value)
        {
            if (mode == BrainSourceMode.Replay)
            {
                if (selectedLines == null || replay.CurrentFrameIndex < 0 || replay.CurrentFrameIndex >= selectedLines.Length) return "N/A";
                var m = Regex.Match(selectedLines[replay.CurrentFrameIndex], "\"" + key + "\"\\s*:\\s*(-?[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)");
                return m.Success ? m.Groups[1].Value : "N/A";
            }
            return value.HasValue ? N(value.Value) : "N/A";
        }
        void Grip(out int attached, out float utilization, out int detach)
        {
            attached = 0; utilization = 0; detach = 0;
            foreach (var leg in body.Legs) if (leg.FootAdhesion != null)
            { attached += leg.FootAdhesion.Attached ? 1 : 0; utilization = Mathf.Max(utilization, leg.FootAdhesion.GripUtilization); detach += leg.FootAdhesion.DetachCount; }
        }
        static string N(float v) => v.ToString("0.###", CultureInfo.InvariantCulture);
        string DisplayRaw(string key,float? value)
        {
            string raw=Raw(key,value);
            return double.TryParse(raw,NumberStyles.Float,CultureInfo.InvariantCulture,out double number)?number.ToString("0.##",CultureInfo.InvariantCulture):raw;
        }
        void OnGUI()
        {
            if (Flylingual.Conversation.NativeConversationRuntime.Enabled) return;
            if (Flag("-demoNoHud")) return;
            if (titleStyle == null)
            {
                titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 27, fontStyle = FontStyle.Bold, normal = { textColor = new Color(.98f,.9f,.67f) } };
                textStyle = new GUIStyle(GUI.skin.label) { fontSize = 17, normal = { textColor = new Color(.88f,.92f,.91f) } };
                smallStyle = new GUIStyle(textStyle) { fontSize = 13, wordWrap = true };
                buttonStyle = new GUIStyle(GUI.skin.button) { fontSize = 13, fixedHeight = 31 };
            }
            Matrix4x4 previousMatrix=GUI.matrix;
            float scale=Mathf.Min(Screen.width/1440f,Screen.height/900f);
            GUI.matrix=Matrix4x4.TRS(Vector3.zero,Quaternion.identity,Vector3.one*scale);
            GUI.color = new Color(.055f,.1f,.12f,.96f); GUI.DrawTexture(new Rect(22,22,354,850), Texture2D.whiteTexture); GUI.color = Color.white;
            GUILayout.BeginArea(new Rect(40,35,318,825));
            GUILayout.Label("FLY / ASCENT", titleStyle);
            var identityFrame = mode == BrainSourceMode.Replay ? replay.LatestFrame : client.LatestBrainFrame;
            bool maleCns = identityFrame?.metadata?.backendId == "MALECNS_EXPERIMENTAL";
            GUILayout.Label(maleCns ? (mode == BrainSourceMode.Replay ? "Backend: MALECNS REPLAY" : "Backend: MALECNS EXPERIMENTAL / " + client.ConnectionState) : mode == BrainSourceMode.Replay ? "Backend: REPLAY\nShiu Brain Recording" : "Backend: LIVE / " + client.ConnectionState, textStyle);
            if (maleCns) GUILayout.Label(identityFrame.metadata.model + "\n" + identityFrame.metadata.motor_readout + " / ready=" + identityFrame.metadata.ready.ToString().ToLowerInvariant(), smallStyle);
            GUILayout.Label(browserControlled ? "Controlled from the browser" : "A small body. A recorded brain.", smallStyle); GUILayout.Space(13);
            var f = mode == BrainSourceMode.Replay ? replay.LatestFrame : client.LatestBrainFrame;
            client.TryGetLatestFrame(out _,out double liveAge);
            GUILayout.Label("ACTION  " + (f?.requestedAction ?? "N/A"), textStyle);
            GUILayout.Label("Sequence " + (f == null ? "N/A" : f.sequence.ToString()) + "   applied ID " + (mode == BrainSourceMode.Replay ? "N/A" : f == null || f.appliedRequestId == 0 ? "none" : f.appliedRequestId.ToString()), smallStyle);
            GUILayout.Label("DNp09      " + DisplayRaw("DNp09_Hz", f?.brain?.DNp09_Hz) + " Hz", textStyle);
            GUILayout.Label("DNa02 R   " + DisplayRaw("DNa02_R_Hz", f?.brain?.DNa02_R_Hz) + " Hz", textStyle);
            GUILayout.Label("DNa02 L    " + DisplayRaw("DNa02_L_Hz", f?.brain?.DNa02_L_Hz) + " Hz", textStyle);
            GUILayout.Label("Forward  " + (f?.motor == null ? "N/A" : N(f.motor.forward)) + "   Turn  " + (f?.motor == null ? "N/A" : N(f.motor.turn)), textStyle);
            if (maleCns && f?.raw?.populationDeltaMv != null)
            {
                var p=f.raw.populationDeltaMv;
                GUILayout.Label("VNC delta mV F L/R: " + (p.forward==null?"N/A":N(p.forward.L)+" / "+N(p.forward.R)) + "\nVNC delta mV T L/R: " + (p.turn==null?"N/A":N(p.turn.L)+" / "+N(p.turn.R)),smallStyle);
            }
            Grip(out int attached, out float utilization, out int detach);
            GUILayout.Label("GRIP   " + attached + "/6 attached", textStyle);
            foreach(var leg in body.Legs)
            {
                var adhesion=leg.FootAdhesion;
                GUILayout.BeginHorizontal();
                GUILayout.Label(leg.LegId,smallStyle,GUILayout.Width(32));
                Rect bar=GUILayoutUtility.GetRect(145,12,GUILayout.Width(145));
                GUI.color=new Color(.15f,.23f,.24f);GUI.DrawTexture(bar,Texture2D.whiteTexture);
                if(adhesion!=null && adhesion.Attached)
                {GUI.color=new Color(.4f,.85f,.65f);GUI.DrawTexture(new Rect(bar.x,bar.y,bar.width*Mathf.Clamp01(adhesion.GripUtilization),bar.height),Texture2D.whiteTexture);}
                GUI.color=Color.white;
                GUILayout.Label(adhesion==null?"N/A":adhesion.Attached?"ATTACHED":"FREE",smallStyle);
                GUILayout.EndHorizontal();
            }
            GUILayout.Label("Bars: measured grip load (free = zero)\nPeak load "+N(utilization*100)+"% / Detach events "+detach,smallStyle);
            string state = emergency ? "EMERGENCY PAUSE" : mode == BrainSourceMode.Replay ? (replay.HasFreshFrame ? "PLAYING" : "RECORDING ENDED") : !waitingForLiveFrame && client.ConnectionState=="CONNECTED" && liveAge<=.75 ? "FRESH" : "STALE / SAFE STOP";
            if(game!=null && game.enabled && game.Current!=AscentGameSession.Phase.Running) state=game.Current==AscentGameSession.Phase.Ready?"READY TO EXPLORE":game.Current==AscentGameSession.Phase.Goal?"GOAL REACHED":"FALLEN / TRY AGAIN";
            GUILayout.Label(state, textStyle);
            GUILayout.Label(mode == BrainSourceMode.Replay ? "Playback frame age " + N((float)(Time.realtimeSinceStartupAsDouble-frameAt)) + " s / E2E N/A" : "Frame age " + (double.IsInfinity(liveAge)?"N/A":N((float)liveAge)+" s") + " / E2E " + (client.LatestLatencyMs<0?"N/A":client.LatestLatencyMs.ToString("0")+" ms"), smallStyle);
            if (!string.IsNullOrEmpty(error)) GUILayout.Label(error, smallStyle);
            if (browserControlled)
            {
                GUILayout.EndArea();
                GUI.matrix = previousMatrix;
                return;
            }
            GUILayout.Space(8); GUILayout.Label(mode == BrainSourceMode.Replay ? "STIMULATE / RECORDED CIRCUITS" : "SEND BRAIN STIMULUS", smallStyle);
            bool gameAllows=game==null || !game.enabled || game.Current==AscentGameSession.Phase.Running;
            GUI.enabled=gameAllows && (mode==BrainSourceMode.Replay || (!waitingForLiveFrame && !emergency && client.ConnectionState=="CONNECTED"));
            for (int row=0; row<2; row++) { GUILayout.BeginHorizontal(); for(int col=0;col<3;col++) { string a=actions[row*3+col]; if(GUILayout.Button(a,buttonStyle)) { if(mode==BrainSourceMode.Replay) SelectReplay(a); else client.SetAction(a); } } GUILayout.EndHorizontal(); }
            GUI.enabled=gameAllows;
            GUILayout.BeginHorizontal();
            GUI.enabled=gameAllows && mode==BrainSourceMode.Replay;
            if(GUILayout.Button("ALL 6",buttonStyle)) SelectReplay("ALL");
            GUI.enabled=gameAllows;
            if(GUILayout.Button("RESTART",buttonStyle)) RestartDemo();
            if(GUILayout.Button("E-STOP",buttonStyle)) PauseDemo();
            GUILayout.EndHorizontal();
            GUI.enabled=game==null || !game.enabled;
            GUILayout.BeginHorizontal(); loop = GUILayout.Toggle(loop,"Loop recording"); if(GUILayout.Button(mode==BrainSourceMode.Replay?"Live TCP":"Replay",buttonStyle)) SetMode(mode==BrainSourceMode.Replay?BrainSourceMode.LiveTcp:BrainSourceMode.Replay); GUILayout.EndHorizontal();
            GUI.enabled=true;
            GUILayout.EndArea();
            if(game==null || !game.enabled) GUI.Label(new Rect(Screen.width/scale-400,Screen.height/scale-54,380,40), mode==BrainSourceMode.Replay?"REPLAY BENCHMARK\nPhysics-driven legs":"LIVE INTEGRATION\nPhysics-driven legs", smallStyle);
            GUI.matrix=previousMatrix;
        }
        public void RestartDemo()
        {
            if (GameSceneTransition.IsLoading) return;
            PauseDemo();
            GameSceneTransition.TryLoad(gameObject.scene.path, message =>
            {
                error = message;
                Debug.LogError("GAME_SCENE_RESTART_FAILED " + message);
            });
        }
        public void PauseDemo() {emergency=true;controller.SetMotorSource(null);Time.timeScale=0;if(!browserControlled && mode==BrainSourceMode.LiveTcp && client.ConnectionState=="CONNECTED") client.SetAction("STOP");}
        [Serializable] class Validation
        {
            public string backend, unityVersion;
            public int recordedFrames,observedFrames,skippedFrames,physicsJoints,footPads,visualPhysicsComponents;
            public float frameTimeP95Ms,fixedDeltaTime,maxVisualEndpointError;
            public string e2e="N/A: offline playback";
        }
        void OnDestroy()
        {
            renderTimes.Sort();
            var report=new Validation { backend=mode.ToString(),unityVersion=Application.unityVersion,recordedFrames=replay.FrameCount,observedFrames=observedFrames,skippedFrames=skippedFrames,
                physicsJoints=jointCount,footPads=footCount,
                visualPhysicsComponents=visualPhysicsCount,
                frameTimeP95Ms=renderTimes.Count==0?0:renderTimes[Mathf.Min(renderTimes.Count-1,Mathf.CeilToInt(renderTimes.Count*.95f)-1)],fixedDeltaTime=Time.fixedDeltaTime,maxVisualEndpointError=ReferenceEquals(mapper,null)?0:mapper.MaximumEndpointError };
            if (browserControlled) report.e2e = "N/A: receive-only BrainFrame observer";
            if(!string.IsNullOrEmpty(output)) File.WriteAllText(Path.Combine(output,"validation_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+".json"),JsonUtility.ToJson(report,true));
            if (!Flylingual.Conversation.NativeConversationRuntime.Enabled)
                Debug.Log(browserControlled ? "BROWSER_BODY_VALIDATION observedFrames=" + observedFrames : "REPLAY_VALIDATION skippedFrames="+skippedFrames);
            samples?.Dispose(); if(client!=null) client.Disconnect();
            if (!GameSceneTransition.IsLoading && !Flylingual.Conversation.NativeConversationRuntime.Enabled) Time.timeScale=1;
        }
    }
}
