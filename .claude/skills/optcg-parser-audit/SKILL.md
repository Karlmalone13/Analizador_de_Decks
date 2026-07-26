---
name: optcg-parser-audit
description: Mandatory workflow for fixing a card-text parsing bug in gerar_effects_db.py or card_effects_db.json (the OPTCG text-to-effects parser in scriptis_da_ia/). Use this whenever a card's parsed effect looks wrong, a card is missing an effect it should have, or a bug is traced back to the parser/effects grammar — even if only one card revealed the problem. Also use proactively before touching gerar_effects_db.py, card_effects_db.json, or scriptis_da_ia/parser_audits/ for any reason. Do NOT use for pure engine-logic bugs in decision_engine.py that don't involve the parser output itself — see optcg-release-handoff for the general commit/push checklist instead.
---

# OPTCG parser audit workflow

## Why this exists

A parser bug found via one card is almost never isolated to that card — the
same clause order, verb synonym, or phrasing variant shows up on other cards
in the 2600+-card database. Fixing only the card that revealed the bug means
the next new card with the same *form* (different words, same grammar shape)
breaks again and costs another investigation. This project has hit that
pattern enough times that a global search before fixing is a hard
requirement, enforced mechanically by a pre-commit hook
(`scripts/verify_parser_global_audit.py`) that blocks the commit if a diff
touches `gerar_effects_db.py` or `card_effects_db.json` without a matching
registration file.

Read `AGENTS.md`/`CLAUDE.md`'s "Gate obrigatório: auditoria global do
parser" section for the full rule text before starting — this skill is the
step-by-step execution of that rule, not a replacement for it.

## Steps

Run everything from `scriptis_da_ia/` unless noted.

1. **Snapshot before touching anything.** Note the current parsed output for
   the affected card(s) (or run whatever snapshot step `diff_parser.py`
   expects — check its `--help` if unsure) so you have a true "before" to
   diff against later.

2. **Search the whole database for the same grammar**, not just the one
   card. Grep `cards_rows.csv` (raw card text) and/or `card_effects_db.json`
   (already-parsed output) for the pattern that caused the bug: the same
   clause order, the same verb (and its synonyms — "K.O." vs "trash" vs
   "remove from the field" describe different mechanics, don't conflate
   them), the same phrasing shape with different card names/numbers. The
   goal is to find every card that *would* hit the same bug, not just
   confirm the one you already know about.

3. **Fix the FORM of the problem, not the specific card.** A regex or
   condition update should generalize to the shape of the text (e.g. "up to
   N targets" for any N, not hardcoded for the 2 targets the revealing card
   happened to have). If you're tempted to special-case the card's exact
   name or number, stop — that's the anti-pattern this whole workflow exists
   to prevent. See the `place_opp_character_bottom_deck` fix referenced in
   `AGENTS.md`/`CLAUDE.md` for a worked example of "generalize to the form."

4. **If the search only turns up the original card** (no others share the
   grammar), that's fine — register the fix with reason
   `isolated_after_global_scan` so future readers know the global search
   genuinely happened and came back empty, rather than being skipped.

5. **Regenerate the databases** in order:
   `gerar_effects_db.py` → `card_effects_db.json` → `gerar_card_analysis_db.py`
   → `card_analysis_db.json`.

6. **Re-run `diff_parser.py`.** `PERDEU=0` (nothing "lost" relative to the
   pre-fix snapshot) is the expected/passing result — investigate before
   proceeding if anything shows as lost, since that means the fix broke
   parsing for cards that worked before.

7. **Write the registration file** in `scriptis_da_ia/parser_audits/`
   (check existing files in that directory for the current naming/format
   convention — keep it consistent). It must document: what pattern/grammar
   was searched for, how many cards matched, what changed for each, and
   the reason code if isolated. This file is what the pre-commit hook
   checks for — a diff touching the parser files without one will be
   blocked.

8. **Run the test suite.** `python smoke_fast.py` always. Run the broader
   `python smoke_test.py` too if the change touches shared grammar used
   across many cards (counters, immunity, substitution effects, or other
   parser-wide logic) rather than a narrow one-off pattern — see
   `AGENTS.md`/`CLAUDE.md` for the current guidance on when the broad suite
   is warranted.

9. **Commit**, including the registration file alongside the code/data
   changes. Then continue into the normal end-of-session checklist (see the
   `optcg-release-handoff` skill) if you're wrapping up the session.

## When you're unsure a fix is "generic enough"

This is a judgment call, not something to rubber-stamp. If you're not
confident the fix covers the real shape of the problem (versus just
patching around the specific symptom), say so explicitly and ask before
committing — a narrow fix that passes the mechanical gate (because you wrote
a registration file) but doesn't actually generalize defeats the point of
this whole workflow.
