using UnityEngine;

namespace FlyVisualDemo
{
    // Game rules only: all movement continues to come from recorded BrainFrame.motor.
    public sealed class AscentGameSession : MonoBehaviour
    {
        public enum Phase { Ready, Running, Fallen, Goal }
        public WindowsReplayDemo demo;
        public Vector3 goal = new Vector3(0, 1f, 4.5f);
        public float goalRadius = .85f;
        public Phase Current { get; private set; }
        public float Elapsed { get; private set; }
        bool benchmark;
        readonly System.Collections.Generic.HashSet<KeyCode> keys = new System.Collections.Generic.HashSet<KeyCode>();
        readonly System.Collections.Generic.Dictionary<KeyCode,float> pulseUntil = new System.Collections.Generic.Dictionary<KeyCode,float>();
        string heldAction = "STOP";
        GUIStyle heading, text, button;
        float orbit, zoom = 1;
        public float Orbit => orbit;
        public float Zoom => zoom;
        // The visual source places the head center 1.04 units forward of thorax.
        // Reaching sugar is a head-contact goal, not a thorax-center overlap.
        public Vector3 GoalProbe => demo.body.Position + demo.body.Thorax.transform.forward*1.04f;

        void Start()
        {
            benchmark = !string.IsNullOrEmpty(WindowsReplayDemo.Argument("-demoAction"));
            if (benchmark) { enabled = false; return; }
            demo.PauseDemo();
        }

        public static Phase Evaluate(Vector3 position, Vector3 target, float radius)
        {
            if (position.y < -3) return Phase.Fallen;
            Vector2 d = new Vector2(position.x-target.x, position.z-target.z);
            if (d.sqrMagnitude <= radius*radius && Mathf.Abs(position.y-target.y) < .45f) return Phase.Goal;
            return Phase.Running;
        }

        public void Begin()
        {
            Current = Phase.Running;
            demo.loop = true;
            demo.SelectReplay("STOP");
            Debug.Log("GAME_BEGIN source=REPLAY_SHIU");
        }
        public void SetRecordedInput(bool forward,bool left,bool right)
        {
            keys.Clear();pulseUntil.Clear();
            if(forward)keys.Add(KeyCode.W);
            if(left)keys.Add(KeyCode.A);
            if(right)keys.Add(KeyCode.D);
        }
        bool Held(KeyCode key)=>keys.Contains(key) || (pulseUntil.TryGetValue(key,out float until) && Time.unscaledTime<until);

        void Update()
        {
            if (Current != Phase.Running) return;
            Elapsed += Time.deltaTime;
            var next = Evaluate(GoalProbe, goal, goalRadius);
            if (next != Phase.Running)
            {
                Current = next;
                demo.PauseDemo();
                Debug.Log("GAME_"+next.ToString().ToUpperInvariant()+" time="+Elapsed+" position="+demo.body.Position);
                return;
            }
            if (demo.mode != WindowsReplayDemo.BrainSourceMode.Replay) return;
            bool forward = Held(KeyCode.W) || Held(KeyCode.UpArrow);
            bool left = Held(KeyCode.A) || Held(KeyCode.LeftArrow);
            bool right = Held(KeyCode.D) || Held(KeyCode.RightArrow);
            string action = left == right ? (forward ? "FORWARD" : "STOP") :
                forward ? (left ? "FORWARD_L" : "FORWARD_R") : (left ? "TURN_L" : "TURN_R");
            // Key release selects the recorded STOP clip. No synthetic motor values.
            if (action != heldAction) { heldAction = action; demo.SelectReplay(action); }
        }

        void OnGUI()
        {
            if (benchmark) return;
            // IMGUI events work with the project's existing input configuration;
            // do not enable the legacy Input API or change global Player settings.
            Event input=Event.current;
            if(input.type==EventType.KeyDown)
            {
                bool first=keys.Add(input.keyCode);
                if(first && (input.keyCode==KeyCode.W || input.keyCode==KeyCode.A || input.keyCode==KeyCode.D || input.keyCode==KeyCode.UpArrow || input.keyCode==KeyCode.LeftArrow || input.keyCode==KeyCode.RightArrow))
                {
                    pulseUntil[input.keyCode]=Time.unscaledTime+.1f;
                    Debug.Log("GAME_KEY_DOWN "+input.keyCode+" buffered=0.1s");
                }
                if(first && input.keyCode==KeyCode.R) { demo.RestartDemo(); return; }
                if(first && input.keyCode==KeyCode.Return && Current==Phase.Ready) Begin();
            }
            if(input.type==EventType.KeyUp) keys.Remove(input.keyCode);
            if(input.type==EventType.MouseDrag && input.button==1) orbit+=input.delta.x*.3f;
            if(input.type==EventType.ScrollWheel) zoom=Mathf.Clamp(zoom+input.delta.y*.025f,.55f,1.8f);
            if (heading == null)
            {
                heading = new GUIStyle(GUI.skin.label) {fontSize=30,fontStyle=FontStyle.Bold,normal={textColor=new Color(1,.89f,.63f)}};
                text = new GUIStyle(GUI.skin.label) {fontSize=17,wordWrap=true,normal={textColor=new Color(.9f,.95f,.93f)}};
                button = new GUIStyle(GUI.skin.button) {fontSize=19,fixedHeight=44};
            }
            var saved = GUI.matrix;
            float scale = Mathf.Min(Screen.width/1440f,Screen.height/900f);
            GUI.matrix = Matrix4x4.Scale(Vector3.one*scale);
            float width = Screen.width/scale;
            Panel(new Rect(402,22,width-426,82));
            GUI.Label(new Rect(424,30,600,28),"01 / THE SUGAR RUN",text);
            float remaining = Vector2.Distance(new Vector2(GoalProbe.x,GoalProbe.z),new Vector2(goal.x,goal.z));
            GUI.Label(new Rect(424,61,700,28),"REACH THE SUGAR   /   "+remaining.ToString("0.0")+" units   /   "+Elapsed.ToString("0.0")+" s",text);
            if(Current != Phase.Running)
            {
                Rect card = new Rect(490,235,650,330);
                Panel(card);
                GUILayout.BeginArea(new Rect(card.x+30,card.y+25,card.width-60,card.height-50));
                GUILayout.Label(Current==Phase.Ready?"A tiny expedition.":Current==Phase.Goal?"SWEET ARRIVAL":"OFF THE EDGE",heading);
                GUILayout.Space(16);
                GUILayout.Label(Current==Phase.Ready?"Cross the desk and reach the sugar. Your inputs select real Shiu brain recordings; the six legs remain driven by physics.":Current==Phase.Goal?"You reached the sugar in "+Elapsed.ToString("0.0")+" seconds.":"The desk has no safety net. Try a different recorded steering sequence.",text);
                GUILayout.Space(20);
                GUILayout.Label("W / A / D  Recorded circuits     R  Restart\nRight-drag  Orbit camera     Wheel  Zoom",text);
                GUILayout.Space(18);
                if(GUILayout.Button(Current==Phase.Ready?"BEGIN EXPEDITION  [ENTER]":"TRY AGAIN  [R]",button))
                {if(Current==Phase.Ready) Begin();else demo.RestartDemo();}
                GUILayout.EndArea();
            }
            GUI.Label(new Rect(424,Screen.height/scale-72,900,28),"W FORWARD   /   A LEFT   /   D RIGHT   /   R RESTART   /   RIGHT-DRAG ORBIT",text);
            GUI.matrix=saved;
        }
        void OnApplicationFocus(bool focused)
        {
            if(focused) return;
            keys.Clear();pulseUntil.Clear();heldAction="STOP";
            if(Current==Phase.Running && demo.mode==WindowsReplayDemo.BrainSourceMode.Replay) demo.SelectReplay("STOP");
        }
        static void Panel(Rect rect)
        {
            Color old=GUI.color;GUI.color=new Color(.025f,.065f,.075f,.94f);
            GUI.DrawTexture(rect,Texture2D.whiteTexture);GUI.color=old;
        }
    }
}
