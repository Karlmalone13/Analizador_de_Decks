---
name: optcg-live-log-triage
description: Mandatory workflow whenever a new OPTCG combat log arrives — the user pastes log content directly, references a .log file path, or asks to investigate/review a match. Adds the log to the versioned log database and, if the bot actually played (not human vs human), reads decision telemetry before reporting on bot performance. Use this any time a combat log needs to be banked or a match needs investigating, even if the user doesn't explicitly ask to "add it to the database." Do NOT use for general engine/parser bugs unrelated to a specific match log — see optcg-parser-audit or the engine docs for those.
---

# OPTCG live log triage workflow

## Why this exists

Combat logs disappear when the simulator updates or reinstalls (has happened
before) and are the raw material for the project's log database and
efficiency reporting. Skipping the "add to database" step because a task
felt done without it has caused real data loss in the past. Separately,
investigating a bot-played match by eyeballing the combat log alone
undercounts real decision-quality bugs — the aggregate telemetry report
often reveals an actual root cause that the raw log's play-by-play print
never surfaces (e.g. a card that never even became a scoring candidate). See
`AGENTS.md`/`CLAUDE.md`'s "Banco de logs" and "Telemetria de decisão"
sections for the full rules this skill executes.

## Step 1 — Get the log into the database

Always do this first, regardless of what the user actually asked for.

If the log content was pasted directly in the conversation (not an existing
file path), save the raw text to a file first — don't skip banking it just
because it didn't arrive as a ready-made path.

```bash
cd scriptis_da_ia
python parse_combat_log.py <caminho_do.log> --add-to-db
```

This copies/renames into `scriptis_da_ia/logs/{raw,parsed,decks}/` and
updates `logs/index.json` using the project's naming convention
(`{LiderSlug-Cores}_x_{LiderSlugOponente-Cores}_{timestamp}.log/json` for
combat logs, `{LiderSlug-Cores}_{timestamp}.json` for reconstructed decks).
Never invent a different folder or naming convention for this — the log
database format is fixed and other tooling depends on it.

## Step 2 — Determine if telemetry reading applies

Telemetry reading is mandatory **only** when the bot actually played in this
match (not a human-vs-human log). If it's human vs human, stop here — the
log is banked and that satisfies this skill.

If the bot played:

- **Local session** (filesystem access to `BOT/engine_server/logs/` and
  `scriptis_da_ia/metrics/live_runs/`, both gitignored/local-only): reading
  telemetry is required and unconditional before reporting the match as
  investigated. Never substitute "I looked at the combat log" for this step.
- **Remote/cloud session** (no access to those paths): they genuinely don't
  exist in this environment. State that explicitly — "telemetria de decisão
  indisponível nesta sessão, é gitignored e local-only" — rather than
  reconstructing bot intent from the raw combat log and presenting that as a
  complete investigation. Guessing from the combat log alone has produced
  wrong conclusions before specifically because of this gap.

## Step 3 — Read telemetry in this order (local sessions only)

Never jump to the second file without reading the first — the aggregate
report tells you *where* to look before you spend time reading
decision-by-decision detail that has no priority signal on its own.

1. **`metrics/live_runs/live_<timestamp>.json`** first, always. Check
   `gate_status`, `bot_confusion` (including `client_timeouts`, which is
   distinct from `no_eligible_action`), `attack_quality`
   (`under_target_count`/`don_planned_total`), `resource_signals`, and
   especially `instrumentation.score_components_coverage_pct`/
   `line_search_coverage_pct` — when these are below 100%, part of the
   match's decisions have no recorded data to audit at all, regardless of
   step 2. A low `mean_counterfactual_regret` does not prove a good
   decision — it only measures against what the search actually simulated;
   an option that never became a candidate never enters that number.
2. **`python decision_summary.py --latest`** (or `--receipt <path>` for a
   specific one) — only after step 1, to dig into whatever it flagged as
   suspicious. Shows the exact action chosen versus the best discarded
   alternatives with their scores, for each bot decision.

## Step 4 — If the bot LOST, run audit_real_losses.py (mandatory)

Whenever the banked log is a loss for the bot side (check `winner` in the
`logs/index.json` entry, or `bot_side` losing in the parsed log), run:

```bash
python audit_real_losses.py --log parsed/<canonical_name>.json
```

This is **mandatory**, not optional or "if there's time" — pedido explícito
do usuário 09/08/2026, depois de uma sessão inteira reagindo decisão-a-decisão
a partir só do combat log e da telemetria sem essa segunda opinião. It
reconstructs the game state turn-by-turn from the historical snapshot and
asks TODAY's engine (`OPTCGMatch.play_turn()`, the real engine, not a
duplicate) what it would do — giving independent corroboration (or
contradiction) for whatever the combat log/telemetry investigation already
suggested, instead of relying on your own read of the raw log alone. Read
the resulting `metrics/real_loss_audits/<nome_do_log>.json` report before
concluding the investigation, and run `python triage_real_losses.py`
afterward to classify each audited turn as MATCH (today's engine repeats
the historical action — a stronger signal worth a closer look) vs DIVERGE
(today's engine does something different — priority signal for manual
review, not an automatic verdict either way).

Skip only when the match is human-vs-human (no bot side to audit) or the
bot won (the tool is specifically for losses — see its own docstring for
why). Read the tool's documented limitations (top of `audit_real_losses.py`)
before treating any single turn's divergence as a confirmed bug — deck
order is shuffled (not the real historical order), opponent hand starts
fully known (more information than the live bot had), and DON tracking is
best-effort. Use it as a second opinion to weigh against the combat-log
investigation, not a verdict on its own.

## Step 5 — Compare against human play where relevant

If the investigation calls for it, `compare_vs_human.py` reconstructs
GameState from a snapshot and runs the Turn Planner to surface turn-by-turn
divergences between what the bot did and what a human did in a similar
spot.

## Step 6 — Report efficiency with numbers

Don't narrate "the bot was inefficient" without a number attached. Run:

```bash
python bot_efficiency_report.py --manifest <cohort>
```

There's no fixed "current" cohort — update or create the manifest
(`metrics/*.json`, schema in `metrics/bot_efficiency_cohorts.json`) with the
matches actually relevant to this investigation (same leader, same time
period) before running the report, otherwise it reports on stale matches and
misleads. The two metrics that matter most for spotting inefficiency:
`dano_por_jogo` (total damage per match) and `don_observado_por_ataque`
(average DON attached when the bot attacks — low values point to a
curve/ramp problem, not just bad luck).

## Step 7 — Scope check

If this triage surfaces a real bug in bot decision-making, that's a
legitimate follow-up but generally a separate task from this skill —
this skill's job is getting the log banked and the telemetry read/reported,
not fixing `decision_engine.py`. Say what you found and ask whether to
pursue the fix now or register it as a pending item (see
`optcg-release-handoff` for how to record it in `HANDOFF.md`/`TODO.md`).
