---
name: optcg-release-handoff
description: End-of-session checklist before committing and pushing work in this OPTCG repo — status check, running the right test suite, writing the HANDOFF.md and TODO.md entries, then commit/push. Use this whenever wrapping up a session, whenever the user asks to commit/push/finish up, or proactively before any push regardless of what was worked on, since no session sees another session's conversation history and HANDOFF.md/TODO.md are the only handoff mechanism between them. Do NOT use this for the actual investigation/fix work itself — this is the wrap-up procedure that comes after.
---

# OPTCG release handoff workflow

## Why this exists

Claude Code and Codex sessions both work on this repo, and neither sees the
other's conversation — only the state of the files. If a session doesn't
write down what it did, the next session (possibly a different tool
entirely) has to reconstruct everything from a bare git log. `HANDOFF.md`
and `TODO.md` are the whole mechanism for that, and it's mechanically
enforced: a `pre-push` hook blocks the push if neither file changed in the
commits being sent. This skill is what to do *before* that hook would fire,
so the block never actually triggers in practice.

## Steps

1. **Check real state first, not conversation memory.** Run
   `git log --oneline -10` and `git status`. Another session may have
   touched the repo since this conversation started — never assume the
   working tree matches what you remember deciding.

2. **Run the test suite that matches what changed.**
   - Python engine/bot changes: `python smoke_fast.py` always. Add the
     broader `python smoke_test.py` if the change touched parser grammar,
     counters, immunity, substitution, or other shared high-risk logic
     (see `AGENTS.md`/`CLAUDE.md` for the current guidance on when the
     broad suite is warranted versus overkill).
   - Frontend changes: `npx eslint`, `npx tsc --noEmit`, and
     `npx next build` before considering the work done.
   - Don't skip this because the change "looked small" — that's exactly
     the kind of change that regresses quietly.

3. **Write a new block at the top of `HANDOFF.md`.** Number it
   sequentially from whatever the current top block's number is. Follow the
   existing format already in the file (date, session type/author, one-line
   summary heading, then the detailed body: what was done, what was found,
   what's still open). Read a couple of the most recent existing blocks
   first if unsure of the exact style — consistency here matters more than
   any specific template.

4. **Reflect the same delta at the top of `TODO.md`.** This is a shorter,
   state-oriented version of the HANDOFF block: what closed, what's still
   pending validation, what changed priority. `TODO.md` going stale while
   `HANDOFF.md` keeps advancing has caused real confusion before — don't
   let one move without the other.

5. **Before any commit/push that's destructive or broad in scope**
   (force-push, resetting branches, `git add -A`-style broad staging),
   pause and confirm it's actually authorized for this specific action —
   don't extrapolate authorization from an earlier, narrower approval.

6. **Commit and push.** This repo's convention is single-line commit
   messages (the working environment is CMD/PowerShell-oriented) — check
   recent commits for the current message style if unsure. Never use
   `git add -A`; stage specific files.

7. **The hooks are a backstop, not the primary mechanism.** `pre-commit`
   prints the project's memory rules and blocks on a few mechanical
   patterns (missing parser-audit registration, suspected duplicate-engine
   logic in `sim_bridge.py`/`server.py`/`bot_optcgsim.py`); `pre-push`
   blocks if `HANDOFF.md` or `TODO.md` didn't change. Do steps 3-4
   proactively rather than relying on the hook to catch a missed update —
   by the time the hook fires, the commit already needs redoing.
   `scripts/setup-git-hooks.sh` installs both hooks fresh in any
   clone/machine, since `.git/hooks/` isn't versioned by git.
