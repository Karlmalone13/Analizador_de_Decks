#!/usr/bin/env python3
"""Relatorio reproduzivel de eficiencia observavel em combat logs.

Exemplos:
    python bot_efficiency_report.py
    python bot_efficiency_report.py --json metrics/report.json
    python bot_efficiency_report.py --proxy baseline_imu_vs_teach.json
    python bot_efficiency_report.py --manifest metrics/meus_cohorts.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
PARSED_ROOT = ROOT / "logs" / "parsed"
DEFAULT_MANIFEST = ROOT / "metrics" / "bot_efficiency_cohorts.json"
COLLECTION_PLAN = ROOT / "metrics" / "evidence_collection_plan.json"
EXPECTED_SNAPSHOT_FIELDS = ("hand", "board", "trash", "life")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _player_leader(data: dict, player: str) -> dict:
    for slot in ("p1", "p2"):
        info = data.get("meta", {}).get("players", {}).get(slot, {})
        if info.get("name") == player:
            return info.get("leader", {})
    return {}


def _opponent_player(data: dict, player: str) -> str | None:
    names = [data.get("meta", {}).get("players", {}).get(s, {}).get("name")
             for s in ("p1", "p2")]
    return next((name for name in names if name and name != player), None)


def _is_leader_target(target: Any, leader: dict) -> bool:
    if isinstance(target, dict):
        return target.get("type") == "LEADER" or target.get("code") == leader.get("code")
    text = str(target or "").lower()
    code = str(leader.get("code") or "").lower()
    name = str(leader.get("name") or "").lower()
    return bool((code and code in text) or (name and name in text))


def _match_stats(data: dict, player: str, expected_leader: str, file_name: str) -> dict:
    own_leader = _player_leader(data, player)
    if own_leader.get("code") != expected_leader:
        raise ValueError(
            f"{file_name}: {player} usa {own_leader.get('code')!r}, esperado {expected_leader!r}"
        )
    opponent = _opponent_player(data, player)
    if not opponent:
        raise ValueError(f"{file_name}: oponente nao encontrado")
    opp_leader = _player_leader(data, opponent)

    turns = data.get("turns", [])
    own_turns = [turn for turn in turns if turn.get("player") == player]
    attacks: list[dict] = []
    attaches = 0
    passive_turns = 0
    first_attack_turn = None
    for own_index, turn in enumerate(own_turns, start=1):
        turn_attacks = [a for a in turn.get("actions", []) if a.get("type") == "attack"]
        attacks.extend(turn_attacks)
        attaches += sum(int(a.get("amount") or 0) for a in turn.get("actions", [])
                        if a.get("type") == "attach_don")
        if turn_attacks and first_attack_turn is None:
            first_attack_turn = turn.get("turn")
        if own_index >= 2 and not turn_attacks:
            passive_turns += 1

    snapshot_turns = 0
    snapshot_fields_present = 0
    snapshot_fields_expected = len(turns) * 2 * len(EXPECTED_SNAPSHOT_FIELDS)
    for turn in turns:
        snap = turn.get("snapshot") or {}
        if snap:
            snapshot_turns += 1
        for side in (player, opponent):
            state = snap.get(side, {})
            snapshot_fields_present += sum(field in state for field in EXPECTED_SNAPSHOT_FIELDS)

    leader_hits = [a for a in attacks
                   if _is_leader_target(a.get("target"), opp_leader)
                   and a.get("result") == "hit"]
    return {
        "file": file_name,
        "games": 1,
        "turns": len(turns),
        "own_turns": len(own_turns),
        "attacks": len(attacks),
        "leader_attacks": sum(_is_leader_target(a.get("target"), opp_leader) for a in attacks),
        # O parser marca hit sem quantidade quando o log nao emite "hit for N".
        # Contra lider isso vale ao menos 1 vida; preserva Double Attack quando N>1.
        "damage": sum(max(1, int(a.get("damage") or 0)) for a in leader_hits),
        "counters_forced": sum(len(a.get("countered_by") or []) for a in attacks),
        "passive_turns": passive_turns,
        "first_attack_turn_sum": int(first_attack_turn or 0),
        "games_with_attack": int(first_attack_turn is not None),
        "attach_don_observed": attaches,
        "snapshot_turns": snapshot_turns,
        "snapshot_fields_present": snapshot_fields_present,
        "snapshot_fields_expected": snapshot_fields_expected,
    }


def _sum_matches(matches: list[dict]) -> dict:
    keys = [k for k in matches[0] if k != "file"] if matches else []
    return {key: sum(float(m[key]) for m in matches) for key in keys}


def _ratio(n: float, d: float, scale: float = 1.0) -> float | None:
    return scale * n / d if d else None


METRICS: dict[str, Callable[[dict], float | None]] = {
    "atk_por_turno": lambda s: _ratio(s["attacks"], s["own_turns"]),
    "pct_atk_lider": lambda s: _ratio(s["leader_attacks"], s["attacks"], 100),
    "dano_por_jogo": lambda s: _ratio(s["damage"], s["games"]),
    "counters_arrancados_por_jogo": lambda s: _ratio(s["counters_forced"], s["games"]),
    "turnos_passivos_por_jogo": lambda s: _ratio(s["passive_turns"], s["games"]),
    "primeiro_ataque_turno_medio": lambda s: _ratio(s["first_attack_turn_sum"], s["games_with_attack"]),
    "don_observado_por_ataque": lambda s: _ratio(s["attach_don_observed"], s["attacks"]),
    "snapshot_coverage_pct": lambda s: _ratio(s["snapshot_turns"], s["turns"], 100),
    "snapshot_completeness_pct": lambda s: _ratio(
        s["snapshot_fields_present"], s["snapshot_fields_expected"], 100
    ),
}


def _round(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, 3)


def _bootstrap(matches: list[dict], metric: Callable[[dict], float | None],
               samples: int, rng: random.Random) -> list[float]:
    if not matches:
        return []
    values = []
    for _ in range(samples):
        picked = [matches[rng.randrange(len(matches))] for _ in matches]
        value = metric(_sum_matches(picked))
        if value is not None and math.isfinite(value):
            values.append(value)
    return sorted(values)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    index = (len(values) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - index) + values[hi] * (index - lo)


def analyze_cohort(cohort: dict, parsed_root: Path, samples: int, seed: int) -> dict:
    matches = []
    for item in cohort.get("matches", []):
        path = parsed_root / item["file"]
        if not path.exists():
            raise FileNotFoundError(f"arquivo do cohort ausente: {path}")
        matches.append(_match_stats(
            _load_json(path), item["player"], cohort["leader_code"], item["file"]
        ))
    total = _sum_matches(matches)
    rng = random.Random(seed)
    metrics = {}
    for name, fn in METRICS.items():
        boot = _bootstrap(matches, fn, samples, rng)
        metrics[name] = {
            "value": _round(fn(total)),
            "ci95": [_round(_percentile(boot, 0.025)), _round(_percentile(boot, 0.975))],
        }
    return {
        "label": cohort["label"],
        "leader_code": cohort["leader_code"],
        "n_games": len(matches),
        "metrics": metrics,
        "availability": {
            "state_fidelity": None,
            "decision_quality": None,
            "execution_success": None,
            "reason": "combat logs atuais nao tem verdade do DTO, snapshot pre-acao ou action_id confirmado",
        },
        "warnings": [
            "DON observado pode subcontar attaches do bot via reflection",
            "intervalos com menos de 20 partidas sao exploratorios",
        ],
        "matches": matches,
    }


def _proxy(path: Path, side: str) -> dict:
    data = _load_json(path)
    stats = data.get(side, {})
    return {
        "source": str(path),
        "side": side,
        "n_games": data.get("n"),
        "seed": data.get("seed"),
        "deck_a": data.get("deck_a"),
        "deck_b": data.get("deck_b"),
        "metrics": stats,
        "warning": "proxy motor-vs-motor; nao mede DTO, bridge, visao ou clique",
    }


def analyze_decision_log(path: Path) -> dict:
    """Agrupa eventos append-only por decision_id e mede cobertura/execucao."""
    result = analyze_decision_events(path.read_text(encoding="utf-8").splitlines())
    result["source"] = str(path)
    return result


def analyze_decision_events(lines) -> dict:
    """Versao testavel em memoria do agregador JSONL."""
    decisions: dict[str, dict] = {}
    executions: dict[str, list[dict]] = {}
    outcomes: list[dict] = []
    decision_errors: list[dict] = []
    client_timeouts: list[dict] = []
    ordered_decisions: list[dict] = []
    commits: set[str] = set()
    sessions: set[str] = set()
    schemas: set[int] = set()
    duplicate_decision_ids = 0
    invalid_lines = 0
    for raw in lines:
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        decision_id = event.get("decision_id")
        if isinstance(event.get("schema"), int):
            schemas.add(event["schema"])
        if event.get("session_id"):
            sessions.add(event["session_id"])
        if not decision_id:
            invalid_lines += 1
            continue
        if event.get("event") == "decision":
            duplicate_decision_ids += int(decision_id in decisions)
            decisions[decision_id] = event
            ordered_decisions.append(event)
            if event.get("commit"):
                commits.add(event["commit"])
        elif event.get("event") == "execution":
            executions.setdefault(decision_id, []).append(event)
        elif event.get("event") == "outcome":
            outcomes.append(event)
        elif event.get("event") == "decision_error":
            # Achado 19/07: excecao real do Python em /decide -- antes disto
            # o evento existia no JSONL mas nunca era lido por este agregador
            # (nem contava em fallback_errors, nem gerava alerta nenhum).
            decision_errors.append(event)
        elif event.get("event") == "client_timeout":
            # Achado 19/07: HttpClient do plugin C# estourou o timeout (10s)
            # esperando resposta de QUALQUER endpoint -- um timeout de rede
            # real, distinto do timeout INTERNO de busca (`timed_out` abaixo,
            # que so mede o join() de 3s da thread de refinamento).
            client_timeouts.append(event)

    confirmed = failed = pending = 0
    with_state_after = 0
    chosen_with_scores = 0
    eligible_recorded = 0
    immediate_gaps = []
    counterfactual_regrets = []
    latencies = []
    timed_out = 0
    fallback_errors = 0
    no_eligible_action = 0
    stuck_executions = 0
    lethal_certified: list[dict] = []
    by_kind: dict[str, dict[str, int]] = {}
    semantic = {"checked": 0, "passed": 0, "failed": 0, "unavailable": 0}

    # Reasons do BotDriver.cs que indicam "o bot decidiu, mas o jogo recusou
    # silenciosamente" (acao repetida sem efeito / ExecuteOne falhou) -- ver
    # BOT/OPTCGBotPlugin/BotDriver.cs, mesma familia de "bot confuso" que
    # no_eligible_action e decision_error, so que descoberta DEPOIS da
    # decisao (na execucao), nao antes.
    _STUCK_EXECUTION_REASONS = ("acao repetida", "ExecuteOne retornou false")

    def find_uid(player: dict, uid: int):
        for zone in ("hand", "board"):
            for card in player.get(zone, []):
                if card.get("deckUniqueId") == uid:
                    return zone, card
        leader = player.get("leader") or {}
        return ("leader", leader) if leader.get("deckUniqueId") == uid else (None, None)

    def main_transition_ok(decision: dict, after: dict) -> bool | None:
        if decision.get("decision_kind") != "main" or not isinstance(after, dict):
            return None
        before = decision.get("state_before") or {}
        response = decision.get("response") or {}
        action = response.get("type")
        uid = response.get("cardId", 0)
        if not before.get("bot") or not after.get("bot"):
            return None
        before_zone, before_card = find_uid(before["bot"], uid)
        after_zone, after_card = find_uid(after["bot"], uid)
        if action == "play":
            return before_zone == "hand" and after_zone != "hand"
        if action == "attack":
            return bool(before_card and after_card and not before_card.get("rested")
                        and after_card.get("rested"))
        if action == "attach_don":
            return bool(before_card and after_card
                        and after_card.get("donAttached", 0) > before_card.get("donAttached", 0))
        if action == "activate":
            if before_card is not None and after_card is None:
                # custo "voce pode trashar este Character" (ex: OP15-026) --
                # a carta some do board como parte do proprio custo, nao e falha.
                return True
            return bool(after_card and after_card.get("actionUsed"))
        if action == "end_turn":
            return after.get("turnNumber") != before.get("turnNumber")
        return None
    for decision_id, decision in decisions.items():
        eligible = [a for a in decision.get("scored_actions", []) if a.get("eligible")]
        if eligible:
            eligible_recorded += 1
        chosen = decision.get("chosen_action")
        kind = decision.get("decision_kind") or decision.get("phase") or "legacy"
        bucket = by_kind.setdefault(kind, {"decisions": 0, "confirmed": 0,
                                           "failed": 0, "pending": 0})
        bucket["decisions"] += 1
        if isinstance(decision.get("latency_ms"), (int, float)):
            latencies.append(float(decision["latency_ms"]))
        timed_out += int(bool(decision.get("timed_out")))
        fallback_errors += int(bool(decision.get("error") or decision.get("telemetry_error")
                                    or decision.get("engine_error")))
        no_eligible_action += int(decision.get("selection") == "no_eligible_action")
        if decision.get("can_lethal"):
            lethal_certified.append(decision)
        if chosen is not None and eligible:
            chosen_with_scores += 1
            best = max(float(a.get("score", -1e9)) for a in eligible)
            immediate_gaps.append(max(0.0, best - float(chosen.get("score", best))))

        events = executions.get(decision_id, [])
        with_state_after += int(any(e.get("state_after") is not None for e in events))
        terminal = next((e for e in reversed(events)
                         if e.get("status") in {"confirmed", "failed"}), None)
        if any(e.get("status") == "failed"
               and any(reason in (e.get("error") or "") for reason in _STUCK_EXECUTION_REASONS)
               for e in events):
            stuck_executions += 1
        if terminal is None:
            pending += 1
            bucket["pending"] += 1
        elif terminal.get("status") == "confirmed":
            confirmed += 1
            bucket["confirmed"] += 1
        else:
            failed += 1
            bucket["failed"] += 1

        # So avaliar semantica quando a execucao foi de fato confirmada --
        # "failed" ja fica registrado por execution_success_pct; reavaliar a
        # semantica sobre um terminal "failed" so duplica o mesmo alerta sem
        # informacao nova.
        terminal_state = terminal.get("state_after") if terminal else None
        semantic_result = (main_transition_ok(decision, terminal_state)
                           if terminal and terminal.get("status") == "confirmed"
                           else None)
        if semantic_result is None:
            semantic["unavailable"] += 1
        else:
            semantic["checked"] += 1
            semantic["passed" if semantic_result else "failed"] += 1

        search = decision.get("search_values") or []
        if search and chosen:
            def same_action(item):
                action = item.get("action") or {}
                return all(action.get(k) == chosen.get(k)
                           for k in ("type", "card_uid", "target_uid"))
            selected = next((float(x["value"]) for x in search if same_action(x)), None)
            if selected is not None:
                counterfactual_regrets.append(max(float(x["value"]) for x in search) - selected)

    def state_vector(state: dict) -> dict[str, float] | None:
        if not isinstance(state, dict) or "bot" not in state or "opp" not in state:
            return None
        bot, opp = state.get("bot", {}), state.get("opp", {})
        return {
            "life_diff": len(bot.get("life", [])) - len(opp.get("life", [])),
            "hand_diff": len(bot.get("hand", [])) - len(opp.get("hand", [])),
            "board_diff": len(bot.get("board", [])) - len(opp.get("board", [])),
            "don_diff": (bot.get("activeDon", 0) + bot.get("restedDon", 0)
                         - opp.get("activeDon", 0) - opp.get("restedDon", 0)),
        }

    future_samples: dict[str, list[dict[str, float]]] = {"1": [], "3": [], "5": []}
    by_match: dict[str, list[tuple[dict, dict[str, float]]]] = {}
    for decision in ordered_decisions:
        vector = state_vector(decision.get("state_before"))
        if vector is not None:
            by_match.setdefault(decision.get("match_id") or "legacy", []).append(
                (decision, vector))
    for vectors in by_match.values():
        for index, (_, before) in enumerate(vectors):
            for horizon in (1, 3, 5):
                if index + horizon >= len(vectors):
                    continue
                after = vectors[index + horizon][1]
                future_samples[str(horizon)].append(
                    {key: after[key] - before[key] for key in before})
    future_value = {}
    for horizon, samples_at_horizon in future_samples.items():
        future_value[horizon] = {
            "samples": len(samples_at_horizon),
            "mean_delta": {
                key: _round(sum(s[key] for s in samples_at_horizon) / len(samples_at_horizon))
                for key in ("life_diff", "hand_diff", "board_diff", "don_diff")
            } if samples_at_horizon else None,
        }

    total = len(decisions)
    completed = confirmed + failed
    observed_matches = {d.get("match_id") for d in ordered_decisions if d.get("match_id")}
    outcome_matches = {e.get("match_id") for e in outcomes if e.get("match_id")}
    latency_sorted = sorted(latencies)
    latency_p95 = _percentile(latency_sorted, 0.95)
    outcome_coverage = _ratio(len(observed_matches & outcome_matches), len(observed_matches), 100)

    # LETHAL certificado -> o jogo realmente terminou logo em seguida? (19/07,
    # fecha o cruzamento que ficou bloqueado com os 79 combat logs -- o JSONL
    # de decisao NAO sofre o corte do AutoSaved, so o .log bruto do jogo).
    # Agrupa por match: primeiro turno com can_lethal=True, e quantos turnos
    # depois o outcome (se veio "win") aconteceu.
    outcome_by_match = {e.get("match_id"): e for e in outcomes if e.get("match_id")}
    lethal_first_turn: dict[str, int] = {}
    for d in lethal_certified:
        mid = d.get("match_id")
        turn = d.get("turn")
        if mid is None or not isinstance(turn, (int, float)):
            continue
        if mid not in lethal_first_turn or turn < lethal_first_turn[mid]:
            lethal_first_turn[mid] = turn
    lethal_turns_to_close = []
    lethal_never_closed = 0
    for mid, first_turn in lethal_first_turn.items():
        outcome = outcome_by_match.get(mid)
        if outcome is None:
            continue
        final_turn = ((outcome.get("state_final") or {}).get("turnNumber"))
        if outcome.get("result") == "win" and isinstance(final_turn, (int, float)):
            lethal_turns_to_close.append(final_turn - first_turn)
        elif outcome.get("result") in {"loss", "draw", "aborted"}:
            lethal_never_closed += 1
    lethal_summary = {
        "matches_with_lethal_certified": len(lethal_first_turn),
        "matches_closed_after_lethal": len(lethal_turns_to_close),
        "matches_not_closed_after_lethal": lethal_never_closed,
        "mean_turns_to_close": _round(
            sum(lethal_turns_to_close) / len(lethal_turns_to_close)
            if lethal_turns_to_close else None),
    }
    gates = _load_json(COLLECTION_PLAN).get("gates", {}) if COLLECTION_PLAN.exists() else {}
    alerts = []

    def alert(code: str, severity: str, message: str, value=None, threshold=None):
        alerts.append({"code": code, "severity": severity, "message": message,
                       "value": _round(value) if isinstance(value, float) else value,
                       "threshold": threshold})

    execution_pct = _ratio(confirmed, completed, 100)
    state_after_pct = _ratio(with_state_after, total, 100)
    counterfactual_pct = _ratio(len(counterfactual_regrets), total, 100)
    if completed and execution_pct < gates.get("execution_success_pct", 95):
        alert("execution_below_gate", "error", "execucao confirmada abaixo do gate",
              execution_pct, gates.get("execution_success_pct", 95))
    if total and state_after_pct < gates.get("state_after_coverage_pct", 95):
        alert("state_after_below_gate", "error", "cobertura de estado posterior abaixo do gate",
              state_after_pct, gates.get("state_after_coverage_pct", 95))
    if observed_matches and outcome_coverage < gates.get("outcome_coverage_pct", 100):
        alert("outcome_missing", "error", "ha partidas sem outcome correlacionado",
              outcome_coverage, gates.get("outcome_coverage_pct", 100))
    if pending:
        alert("pending_decisions", "warning", "ha decisoes sem confirmed/failed", pending, 0)
    if timed_out:
        alert("decision_timeouts", "error", "a busca excedeu o timeout", timed_out, 0)
    if fallback_errors:
        alert("decision_fallback_errors", "error", "decisoes usaram fallback por erro",
              fallback_errors, 0)
    bot_confusion_total = (no_eligible_action + len(decision_errors)
                          + len(client_timeouts) + stuck_executions)
    if bot_confusion_total:
        alert("bot_confusion", "error",
              f"bot travado/confuso {bot_confusion_total}x (sem_acao={no_eligible_action}, "
              f"excecao_engine={len(decision_errors)}, timeout_cliente={len(client_timeouts)}, "
              f"execucao_travada={stuck_executions})",
              bot_confusion_total, 0)
    if len(commits) > 1:
        alert("mixed_commits", "error", "o mesmo arquivo mistura commits", len(commits), 1)
    if len(sessions) > 1:
        alert("mixed_sessions", "error", "o mesmo arquivo mistura sessoes do server",
              len(sessions), 1)
    if schemas - {1}:
        alert("unsupported_schema", "error", "ha eventos com schema nao suportado",
              sorted(schemas), [1])
    if invalid_lines:
        alert("invalid_jsonl_lines", "error", "ha linhas JSONL invalidas", invalid_lines, 0)
    if duplicate_decision_ids:
        alert("duplicate_decision_ids", "error", "decision_id duplicado no arquivo",
              duplicate_decision_ids, 0)
    if total and counterfactual_pct < gates.get("minimum_counterfactual_coverage_pct", 20):
        alert("counterfactual_coverage_low", "warning",
              "poucas decisoes tiveram alternativas realmente simuladas",
              counterfactual_pct, gates.get("minimum_counterfactual_coverage_pct", 20))
    if semantic["failed"]:
        alert("semantic_transition_failed", "error",
              "DTO mudou, mas a transicao esperada da acao principal nao ocorreu",
              semantic["failed"], 0)
    if latency_p95 is not None and latency_p95 > gates.get("decision_latency_p95_ms", 3000):
        alert("latency_p95_above_gate", "warning", "latencia p95 acima do gate",
              latency_p95, gates.get("decision_latency_p95_ms", 3000))
    return {
        "source": "<memory>",
        "decisions": total,
        "confirmed": confirmed,
        "failed": failed,
        "pending": pending,
        "execution_success_pct": _round(execution_pct),
        "legal_actions_coverage_pct": _round(_ratio(eligible_recorded, total, 100)),
        "chosen_score_coverage_pct": _round(_ratio(chosen_with_scores, total, 100)),
        "state_after_coverage_pct": _round(state_after_pct),
        "mean_immediate_score_gap": _round(
            sum(immediate_gaps) / len(immediate_gaps) if immediate_gaps else None
        ),
        "mean_counterfactual_regret": _round(
            sum(counterfactual_regrets) / len(counterfactual_regrets)
            if counterfactual_regrets else None),
        "counterfactual_coverage_pct": _round(counterfactual_pct),
        "latency_ms": {
            "samples": len(latencies),
            "mean": _round(sum(latencies) / len(latencies) if latencies else None),
            "p95": _round(latency_p95),
            "max": _round(max(latencies) if latencies else None),
            "timeout_count": timed_out,
            "timeout_pct": _round(_ratio(timed_out, total, 100)),
        },
        "commit_consistency": {"commits": sorted(commits), "mixed": len(commits) > 1},
        "session_consistency": {"sessions": sorted(sessions), "mixed": len(sessions) > 1},
        "schemas": sorted(schemas),
        "duplicate_decision_ids": duplicate_decision_ids,
        "outcome_coverage_pct": _round(outcome_coverage),
        "alerts": alerts,
        "gate_status": "fail" if any(a["severity"] == "error" for a in alerts)
                       else "warning" if alerts else "pass",
        "decision_kinds": by_kind,
        "outcomes": {
            "games": len(outcomes),
            "wins": sum(e.get("result") == "win" for e in outcomes),
            "losses": sum(e.get("result") == "loss" for e in outcomes),
            "win_rate_pct": _round(_ratio(
                sum(e.get("result") == "win" for e in outcomes),
                sum(e.get("result") in {"win", "loss"} for e in outcomes), 100)),
        },
        "future_state_delta_by_decisions": future_value,
        "state_fidelity": None,
        "transition_semantics": _round(_ratio(semantic["passed"], semantic["checked"], 100)),
        "transition_semantics_summary": {
            **semantic,
            "success_pct": _round(_ratio(semantic["passed"], semantic["checked"], 100)),
        },
        "decision_quality": None,
        "invalid_lines": invalid_lines,
        "bot_confusion": {
            "total": bot_confusion_total,
            "no_eligible_action": no_eligible_action,
            "engine_exceptions": len(decision_errors),
            "client_timeouts": len(client_timeouts),
            "stuck_executions": stuck_executions,
        },
        "lethal_certified_summary": lethal_summary,
        "notes": [
            "execution_success usa confirmacao por mudanca do DTO no proximo main state estavel",
            "mean_immediate_score_gap nao e arrependimento: busca pode escolher score imediato menor",
            "state_fidelity exige verdade independente do estado do jogo",
            "contrafactual usa somente alternativas realmente simuladas pela busca do motor",
            "sent sem confirmed/failed permanece pending e nao conta como sucesso",
            "bot_confusion agrega sinais de 'nao sabia o que fazer' (sem_acao/excecao/timeout/execucao "
            "travada); lethal_certified_summary correlaciona can_lethal=True com o outcome real da partida",
        ],
    }


def _fmt_metric(metric: dict) -> str:
    value = metric["value"]
    lo, hi = metric["ci95"]
    if value is None:
        return "n/d"
    return f"{value:.3f} (IC95% {lo:.3f}..{hi:.3f})"


def print_report(report: dict) -> None:
    print("=== EFICIENCIA OBSERVAVEL DO BOT ===")
    for cohort in report["cohorts"]:
        print(f"\n[{cohort['label']}] n={cohort['n_games']}")
        for name, metric in cohort["metrics"].items():
            print(f"  {name:34s} {_fmt_metric(metric)}")
        print("  state_fidelity/decision/execution: n/d (telemetria ausente)")
    for proxy in report.get("proxies", []):
        print(f"\n[proxy] {proxy['source']} lado={proxy['side']} n={proxy['n_games']}")
        for name, value in proxy["metrics"].items():
            print(f"  {name:34s} {value}")
    for live in report.get("decision_logs", []):
        print(f"\n[telemetria] {live['source']} decisions={live['decisions']}")
        for name in ("execution_success_pct", "legal_actions_coverage_pct",
                     "chosen_score_coverage_pct", "state_after_coverage_pct",
                     "mean_immediate_score_gap", "mean_counterfactual_regret",
                     "counterfactual_coverage_pct"):
            print(f"  {name:34s} {live[name]}")
        print(f"  {'decision_kinds':34s} {live['decision_kinds']}")
        print(f"  {'outcomes':34s} {live['outcomes']}")
        print(f"  {'future_delta_1_3_5':34s} {live['future_state_delta_by_decisions']}")
        print(f"  {'latency_ms':34s} {live['latency_ms']}")
        print(f"  {'bot_confusion':34s} {live['bot_confusion']}")
        print(f"  {'lethal_certified_summary':34s} {live['lethal_certified_summary']}")
        print(f"  {'gate_status':34s} {live['gate_status']}")
        for alert in live["alerts"]:
            print(f"  ALERTA {alert['severity'].upper():7s} {alert['code']}: {alert['message']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--parsed-root", type=Path, default=PARSED_ROOT)
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20260717)
    ap.add_argument("--proxy", action="append", type=Path, default=[])
    ap.add_argument("--proxy-side", choices=("A", "B"), default="A")
    ap.add_argument("--decision-log", action="append", type=Path, default=[])
    ap.add_argument("--json", dest="json_out", type=Path)
    args = ap.parse_args()

    manifest = _load_json(args.manifest)
    if manifest.get("schema") != 1:
        raise ValueError("manifest schema deve ser 1")
    report = {
        "schema": 1,
        "manifest": str(args.manifest),
        "bootstrap_samples": args.bootstrap,
        "bootstrap_seed": args.seed,
        "cohorts": [
            analyze_cohort(c, args.parsed_root, args.bootstrap, args.seed + i)
            for i, c in enumerate(manifest.get("cohorts", []))
        ],
        "proxies": [_proxy(path, args.proxy_side) for path in args.proxy],
        "decision_logs": [analyze_decision_log(path) for path in args.decision_log],
    }
    print_report(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        print(f"\nSalvo em {args.json_out}")


if __name__ == "__main__":
    main()
