using System;

namespace Flylingual.Conversation
{
    public static class NativeConversationRuntime
    {
        public static bool SceneOptIn;
        public static bool Enabled => Requested || SceneOptIn;
        public static bool Requested
        {
            get
            {
#if FLY_NATIVE_CONVERSATION
                return true;
#else
                return Array.IndexOf(Environment.GetCommandLineArgs(), "-flyConversation") >= 0;
#endif
            }
        }
    }
}
