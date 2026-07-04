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

        private class MulliganResponse
        {
            public bool mulligan;
            public string reason = "";
        }

        public class DefenseResponse
        {
            public int blockerId;
            public System.Collections.Generic.List<int> counterIds = new();
            public bool useTrigger;
        }

        public class TargetCandidate
        {
            public int id;
            public string zone = "";
        }

        private class ChooseTargetResponse
        {
            public System.Collections.Generic.List<int> orderedIds = new();
        }

        // Ordena candidatos de alvo por preferencia do engine. Null em erro.
        public static System.Collections.Generic.List<int>? ChooseTarget(
            GameStateDto state,
            System.Collections.Generic.List<TargetCandidate> candidates,
            string? actorCode = null)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new { state, candidates, actorCode });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/choose_target", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                    return null;
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                return JsonConvert.DeserializeObject<ChooseTargetResponse>(body)?.orderedIds;
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineClient] choose_target: {ex.Message}");
                return null;
            }
        }

        // phase: "blocker" | "counter" | "trigger". Null em erro (defesa conservadora).
        public static DefenseResponse? Defense(GameStateDto state, string phase,
                                               int attackerPower, int defenderPower,
                                               string? triggerCode = null)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new
                {
                    state, phase, attackerPower, defenderPower, triggerCode
                });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/defense", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                    return null;
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                return JsonConvert.DeserializeObject<DefenseResponse>(body);
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineClient] defense: {ex.Message}");
                return null;
            }
        }

        // true = trocar a mao; false = manter (default seguro em erro)
        public static bool ShouldMulligan(System.Collections.Generic.List<CardDto> hand)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new { hand });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/mulligan", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                    return false;
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                var r = JsonConvert.DeserializeObject<MulliganResponse>(body);
                if (r != null)
                    Plugin.Log.LogInfo($"[Bot] mulligan={r.mulligan} ({r.reason})");
                return r?.mulligan ?? false;
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineClient] mulligan: {ex.Message}");
                return false;
            }
        }
    }
}
