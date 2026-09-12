using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.TestTools;
using Flylingual.Conversation;

// Explicit filter only: this test starts the real local Windows Brain via the
// same Unity bootstrap. It supplies no microphone, API prompt, or motor samples.
public sealed class NativeEditorIntegrationTests
{
    [UnityTest, Explicit("Real Windows-local Editor connection lifecycle; no API call")]
    public IEnumerator EditorConnectsToRealBrainAndReleasesOwnedServices()
    {
        EditorSceneManager.OpenScene(NativeConversationBuilder.TestScene);
        yield return new EnterPlayMode();
        ConversationSessionController controller = null;
        float deadline = Time.realtimeSinceStartup + 60;
        while (Time.realtimeSinceStartup < deadline)
        {
            controller = Object.FindAnyObjectByType<ConversationSessionController>();
            if (controller != null && controller.Ready && controller.Sequence > 1) break;
            yield return null;
        }
        bool connected = controller != null && controller.Ready && controller.Sequence > 1;
        bool inhibited = controller != null && controller.OutputInhibited;
        var bootstrap = Object.FindAnyObjectByType<ConversationNativeBootstrap>();
        string statusPath = bootstrap != null ? bootstrap.StatusPath : null;
        yield return new ExitPlayMode();
        double end = UnityEditor.EditorApplication.timeSinceStartup + 30;
        while (UnityEditor.EditorApplication.timeSinceStartup < end)
        {
            if (statusPath != null && File.Exists(statusPath) && File.ReadAllText(statusPath).Contains("\"stopped\"")) break;
            yield return null;
        }
        Assert.That(connected, Is.True, "Editor must observe advancing real Brain sequences");
        Assert.That(inhibited, Is.True);
        Assert.That(statusPath, Is.Not.Null);
        Assert.That(File.ReadAllText(statusPath), Does.Contain("\"stopped\""));
    }
}
