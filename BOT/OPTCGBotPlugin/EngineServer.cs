using System;
using System.Diagnostics;
using System.IO;

namespace OPTCGBotPlugin
{
    // Inicia e encerra o servidor Python (engine_server/server.py) como processo filho
    public static class EngineServer
    {
        private static Process? _proc;

        // Caminho do server.py relativo ao plugin — ajuste se necessario
        private static readonly string _serverScript =
            Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
                         @"..\..\..\..\BOT\engine_server\server.py");

        public static void Start()
        {
            if (!File.Exists(_serverScript))
            {
                Plugin.Log.LogWarning($"[EngineServer] server.py nao encontrado em: {_serverScript}");
                Plugin.Log.LogWarning("[EngineServer] Inicie manualmente: python BOT/engine_server/server.py");
                return;
            }

            try
            {
                _proc = new Process
                {
                    StartInfo = new ProcessStartInfo
                    {
                        FileName  = "python",
                        Arguments = $"\"{_serverScript}\"",
                        UseShellExecute        = false,
                        CreateNoWindow         = true,
                        RedirectStandardOutput = false,
                        RedirectStandardError  = false,
                    }
                };
                _proc.Start();
                Plugin.Log.LogInfo($"[EngineServer] Servidor Python iniciado (PID {_proc.Id})");
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineServer] Falha ao iniciar servidor Python: {ex.Message}");
                Plugin.Log.LogWarning("[EngineServer] Inicie manualmente: python BOT/engine_server/server.py");
            }
        }

        public static void Stop()
        {
            try { _proc?.Kill(); } catch { }
            _proc = null;
        }
    }
}
