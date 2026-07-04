using System;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace OPTCGBotPlugin
{
    // Cliente HTTP que conversa com o servidor Python (engine_server/server.py)
    public static class EngineClient
    {
        private static readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(10) };
        private const string BASE = "http://localhost:8765";

        public static BotAction? Decide(GameStateDto state)
        {
            try
            {
                string json = JsonConvert.SerializeObject(state);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/decide", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                {
                    Plugin.Log.LogWarning($"[EngineClient] HTTP {resp.StatusCode}");
                    return null;
                }
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                return JsonConvert.DeserializeObject<BotAction>(body);
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineClient] {ex.Message}");
                return null;
            }
        }

        public static bool IsAlive()
        {
            try
            {
                var resp = _http.GetAsync($"{BASE}/health").GetAwaiter().GetResult();
                return resp.IsSuccessStatusCode;
            }
            catch { return false; }
        }
    }
}
