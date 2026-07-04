using BepInEx;
using BepInEx.Logging;
using HarmonyLib;

namespace OPTCGBotPlugin
{
    [BepInPlugin("com.optcgbot.plugin", "OPTCG Bot Plugin", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static ManualLogSource Log = null!;
        private Harmony _harmony = null!;

        private void Awake()
        {
            Log = base.Logger;
            _harmony = new Harmony("com.optcgbot.plugin");
            _harmony.PatchAll();

            EngineServer.Start();
            Log.LogInfo("OPTCGBot carregado — servidor engine em localhost:8765");
        }

        private void OnDestroy()
        {
            _harmony.UnpatchSelf();
            EngineServer.Stop();
        }
    }
}
