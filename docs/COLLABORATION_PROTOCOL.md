# Agent Collaboration Protocol

## Roles

| Agent | Primary Responsibilities |
|-------|------------------------|
| **Cascade (Windsurf)** | Code development, live trading ops, debugging, deployment, implementation |
| **Claude** | Code review, research validation, strategy assessment, walk-forward testing, feedback |

The user (Nick) coordinates both agents and makes final deployment decisions.

---

## Message Exchange

### Location: `docs/agent-comms/`

```
docs/agent-comms/
├── cascade-to-claude/
│   └── YYYY-MM-DD_subject.md
└── claude-to-cascade/
    └── YYYY-MM-DD_subject.md
```

### Message Format

```markdown
# [Date] Subject

## Context
1-2 sentences on what prompted this message.

## Content
The actual findings, review, request, or response.

## Action Items
- [ ] Specific items for the other agent
- [ ] Include priority (HIGH/MED/LOW) if relevant
```

### Rules
- Keep messages **short and focused** — one topic per message
- Include **data/evidence** (Sharpe numbers, trade counts, file paths) not just opinions
- Reference specific files/functions when discussing code
- If responding to a previous message, link it: "Re: `cascade-to-claude/2026-03-22_topic.md`"
- Action items must be concrete and testable

---

## Progress Journal

### Location: `docs/journal/`

One entry per significant session. Filename: `YYYY-MM-DD_short-description.md`

### When to Write a Journal Entry (MANDATORY)

Both agents MUST write a journal entry when:
1. A coding session produces code changes (even small ones)
2. Research is run and produces results (successful or not)
3. Live trading events occur (trades, errors, config changes)
4. A significant decision is made (strategy change, parameter update, deployment)

**Rule: If you changed code, ran research, or made a decision — write a journal entry before ending your session.**

### Standard Sections

```markdown
# [Date] Title

## Author
Cascade or Claude

## What Was Done
- Bullet list of completed work with file paths

## What Was Tried (and failed/changed)
- Important for avoiding repeated mistakes
- Include WHY it failed

## Key Decisions & Rationale
- Why we chose X over Y
- Link to data/evidence

## Code Changes
- List of files modified/created with 1-line summary each

## Current State
- What's running, what's deployed, current configs
- Any active processes or pending items

## Next Steps
- Prioritized list with owner (Cascade/Claude)
```

---

## Shared Progress File

### Location: `docs/PROGRESS.md`

A single living document that both agents update. This is the "source of truth" for project status.

### Format

```markdown
# Project Progress

## Active Deployments
| Process | Strategy | Pair | Params | Status | Since |
|---------|----------|------|--------|--------|-------|

## Research Queue
| Task | Priority | Owner | Status | Notes |
|------|----------|-------|--------|-------|

## Completed Research (last 30 days)
| Date | Task | Result | Journal Entry |
|------|------|--------|---------------|

## Known Issues
- [ ] Issue description (owner, date filed)

## Parameter History
| Date | Param | Old Value | New Value | Reason | Validated? |
|------|-------|-----------|-----------|--------|------------|
```

### Update Rules
- **Cascade** updates: Active Deployments, Known Issues, Code Changes
- **Claude** updates: Research Queue, Completed Research, Parameter History
- **Both** update: whatever they touched that session
- Update PROGRESS.md at the END of every session, not the beginning
- Keep it factual — no opinions, just status

---

## Documentation Obligations by Agent

### Cascade MUST document:
1. Every code change (in journal + git commit)
2. Every deployment config change (in PROGRESS.md Parameter History)
3. Every live trading incident (error, unexpected behavior, manual intervention)
4. Session handover context (in journal entry)

### Claude MUST document:
1. Every research run (parameters, results, conclusion — in journal)
2. Every code review finding (in agent-comms message + journal)
3. Every parameter recommendation (in PROGRESS.md + agent-comms)
4. Walk-forward results (in docs/research/ + PROGRESS.md)

### Both agents MUST:
- Write a journal entry for every working session
- Update PROGRESS.md before ending a session
- Commit and push all docs to git
- Reference file paths and line numbers, not vague descriptions

---

## Review Triggers

Claude should review when:
1. New strategy code is pushed (before paper deployment)
2. Research claims need walk-forward validation
3. Before transitioning paper → live (real money)
4. After significant parameter changes
5. When Cascade flags something for review

Cascade should review when:
1. Claude proposes parameter changes that affect live deployment
2. Claude identifies bugs in live code
3. Claude's research produces new deployment configs

---

## File Conventions

| Type | Location | Example |
|------|----------|---------|
| Agent messages | `docs/agent-comms/{sender}-to-{receiver}/` | `cascade-to-claude/2026-03-22_max-hold-sweep.md` |
| Session journals | `docs/journal/` | `2026-03-22_v8-paper-deployment.md` |
| Session handovers | `docs/journal/` | `2026-03-22_session-handover.md` |
| Research docs | `docs/research/` | `multi-instrument-v6-v8-findings.md` |
| Design docs | `docs/design/` | `v8-multi-pair-architecture.md` |

**Do NOT put** session files, response files, or handover docs in the repo root.

---

## Git Practices

- Commit before ending a session
- Push to remote (`origin/v6-refactor` or appropriate branch)
- Commit message format: short summary line + detailed body with file list
- Stage files explicitly (never `git add .` — venv is not gitignored)
