using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OPTCGBotPlugin
{
    [BepInPlugin("com.optcgbot.plugin", "OPTCG Bot Plugin", "1.1.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static ManualLogSource Log = null!;
        private GameObject? _driverGo;
        private Harmony? _harmony;

        private void Awake()
        {
            Log = base.Logger;
            _harmony = new Harmony("com.optcgbot.plugin");
            _harmony.PatchAll();
            Log.LogInfo("[Bot] Harmony PatchAll executado");

            // Driver do bot: MonoBehaviour persistente que age via Update()
            _driverGo = new GameObject("OPTCGBotDriver");
            _driverGo.AddComponent<BotDriver>();
            Object.DontDestroyOnLoad(_driverGo);

            Log.LogInfo("OPTCGBot v1.1 carregado — servidor engine em localhost:8765");
            Log.LogInfo("Inicie o servidor: python BOT/engine_server/server.py");
        }

        private void OnDestroy()
        {
            _harmony?.UnpatchSelf();
            if (_driverGo != null)
                Object.Destroy(_driverGo);
        }
    }
}
