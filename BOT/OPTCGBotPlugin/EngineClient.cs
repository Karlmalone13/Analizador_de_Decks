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

        // Reporta o ciclo de execucao sem tomar nenhuma decisao no plugin.
        // status: sent | confirmed | failed. O decisionId veio de /decide.
        public static void ReportExecution(BotAction action, string status,
                                           GameStateDto? stateAfter, string? error = null)
        {
            if (action == null || string.IsNullOrEmpty(action.decisionId)) return;
            try
            {
                string json = JsonConvert.SerializeObject(new
                {
                    decisionId = action.decisionId,
                    status,
                    stateAfter,
                    error,
                });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/execution", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                    Plugin.Log.LogWarning($"[EngineClient] execution HTTP {resp.StatusCode}");
            }
            catch (Exception ex)
            {
                Plugin.Log.LogWarning($"[EngineClient] execution: {ex.Message}");
            }
        }

        public static void ReportExecutionId(string decisionId, string status,
                                             GameStateDto? stateAfter, string? error = null)
        {
            if (string.IsNullOrEmpty(decisionId)) return;
            ReportExecution(new BotAction { decisionId = decisionId }, status, stateAfter, error);
        }

        public static void ReportOutcome(string result, GameStateDto? stateFinal,
                                         string? reason = null)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new { result, stateFinal, reason });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                _http.PostAsync($"{BASE}/outcome", content).GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                Plugin.Log.LogWarning($"[EngineClient] outcome: {ex.Message}");
            }
        }

        public class CollectionStatus
        {
            public string status = "unknown";
            public string message = "";
            public string? report;
            public string? receipt;
        }

        public static CollectionStatus? GetCollectionStatus()
        {
            try
            {
                var resp = _http.GetAsync($"{BASE}/collection_status").GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode) return null;
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                return JsonConvert.DeserializeObject<CollectionStatus>(body);
            }
            catch { return null; }
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
            public string decisionId = "";
            public bool mulligan;
            public string reason = "";
        }

        private class TurnOrderResponse
        {
            public bool goFirst;
            public string reason = "";
        }

        // Bot ganhou o dado: engine decide 1o/2o pela curva do deck.
        // false em erro (segundo = escolha conservadora de recurso).
        public static bool GoFirst(System.Collections.Generic.List<string> deckCodes)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new { deckCodes });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/turn_order", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                    return false;
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                var r = JsonConvert.DeserializeObject<TurnOrderResponse>(body);
                if (r != null)
                    Plugin.Log.LogInfo($"[Bot] turn_order: goFirst={r.goFirst} ({r.reason})");
                return r?.goFirst ?? false;
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineClient] turn_order: {ex.Message}");
                return false;
            }
        }

        public class DefenseResponse
        {
            public string decisionId = "";
            public int blockerId;
            public System.Collections.Generic.List<int> counterIds = new();
            public bool useTrigger;
            public bool useReaction;
        }

        public class TargetCandidate
        {
            public int id;
            public string zone = "";
            public string code = "";   // cardID — engine valora cartas fora do DTO (trash/top deck)
        }

        private class ChooseTargetResponse
        {
            public string decisionId = "";
            public System.Collections.Generic.List<int> orderedIds = new();
        }

        // Ordena candidatos de alvo por preferencia do engine. Null em erro.
        // attackerPower/defenderId: contexto de ataque em andamento (redirect) —
        // 0 quando o efeito resolve fora de combate.
        public static System.Collections.Generic.List<int>? ChooseTarget(
            GameStateDto state,
            System.Collections.Generic.List<TargetCandidate> candidates,
            string? actorCode = null,
            int attackerPower = 0,
            int defenderId = 0,
            Action<string>? onDecision = null)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new { state, candidates, actorCode, attackerPower, defenderId });
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = _http.PostAsync($"{BASE}/choose_target", content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode)
                    return null;
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                var result = JsonConvert.DeserializeObject<ChooseTargetResponse>(body);
                if (result != null) onDecision?.Invoke(result.decisionId);
                return result?.orderedIds;
            }
            catch (Exception ex)
            {
                Plugin.Log.LogError($"[EngineClient] choose_target: {ex.Message}");
                return null;
            }
        }

        // phase: "blocker" | "counter" | "trigger" | "reaction" | "optional".
        // defenderId: uid do alvo atual do ataque (contexto p/ redirect).
        // Null em erro (defesa conservadora).
        public static DefenseResponse? Defense(GameStateDto state, string phase,
                                               int attackerPower, int defenderPower,
                                               string? triggerCode = null,
                                               int defenderId = 0)
        {
            try
            {
                string json = JsonConvert.SerializeObject(new
                {
                    state, phase, attackerPower, defenderPower, defenderId, triggerCode
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
        public static bool ShouldMulligan(System.Collections.Generic.List<CardDto> hand,
                                          Action<string>? onDecision = null)
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
                if (r != null) onDecision?.Invoke(r.decisionId);
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
