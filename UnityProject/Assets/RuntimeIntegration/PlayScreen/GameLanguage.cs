namespace Flylingual.PlayScreen
{
    /// <summary>English-only title, game UI and conversation language.</summary>
    public static class GameLanguage
    {
        // Legacy preferences and the operating system language do not affect this build.
        public static string Code => "en";
        public static bool IsJapanese => false;
        public static string Text(string ja, string en) => en;

        // Retained for existing diagnostic callers; language switching is no longer supported.
        public static void SetLanguage(string language) { }
    }
}
