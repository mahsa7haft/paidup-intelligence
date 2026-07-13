# Claude Code life hacks I wish I knew before

Transcribed from a LinkedIn post — 25 practical tips for working with Claude Code.

## CLAUDE.md and rules

1. `CLAUDE.md` is your project's rulebook. Claude reads it every session.
2. Run `/init` in a new repo. It writes that `CLAUDE.md` for you.
3. Keep `CLAUDE.md` short. Around 60 lines. A bloated file gets ignored.
4. Split rules into `.claude/rules/*.md` with globs. Each loads only when it matters.
5. Type `#` in chat to save a rule on the spot. It sticks across sessions.

## Context management

6. Use `@file` to pin exact files into context. Don't make Claude hunt for them.
7. `/clear` between unrelated tasks. A stale context makes Claude dumber.
8. `/compact` before it auto-compacts. The model is at its worst when it runs out of room.
9. `/context` shows how full your window is. Read it like a fuel gauge.

## Working style

10. Turn on plan mode first. Claude plans the whole thing before it changes a line.
11. `/loop` repeats a task until it's done. "Fix the tests, keep going until they pass."
12. Pre-approve safe tools in `/permissions`. Stop clicking "yes" on every command.

## Subagents

13. Send research to a subagent. Its file reads stay in its context, not yours.
14. Give each subagent one job. A planner, a reviewer, a debugger. Sharp beats general.
15. Up to 10 subagents run in parallel. Fan out the slow, noisy work.

## Skills

16. Skills live in `.claude/skills/<name>/SKILL.md`. Claude loads the ones that fit.
17. Front-load the skill description. Anything past ~250 characters gets cut.

## Power features

18. `/effort ultracode` for big jobs. Claude splits huge tasks across many agents.
19. Hooks run your own code on events. Block a bad commit before Claude makes it.
20. `/model` picks the brain. Sonnet for daily work, Opus for hard, Fable for the heaviest.
21. `/review` checks changes for bugs. `/security-review` hunts the scary stuff.

## Automation and remote

22. Run `claude -p` headless in a GitHub Action. Reviews every PR with no terminal open.
23. `claude -w` opens a git worktree. Two sessions, two features, zero conflicts.
24. Remote control lets you steer a run from your phone. The session stays on your machine.
25. Routines run jobs on a schedule while you're away. Claude keeps working when you're not there.
