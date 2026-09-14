using UnityEngine;

namespace Flylingual.PlayScreen
{
    /// <summary>Shared title, game UI and conversation language preference.</summary>
    public static class GameLanguage
    {
        const string PreferenceKey = "Flylingual.Language";
        static string code;
        public static string Code => code ?? (code = ReadLanguage());
        public static bool IsJapanese => Code == "ja";
        public static string Text(string ja, string en) => IsJapanese ? ja : en;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetState() => code = null;

        static string ReadLanguage()
        {
            string saved = PlayerPrefs.GetString(PreferenceKey, string.Empty);
            return saved == "ja" || saved == "en" ? saved : Application.systemLanguage == SystemLanguage.Japanese ? "ja" : "en";
        }

        public static void SetLanguage(string language)
        {
            if (language != "ja" && language != "en") return;
            code = language;
            PlayerPrefs.SetString(PreferenceKey, code);
            PlayerPrefs.Save();
        }
    }
}
