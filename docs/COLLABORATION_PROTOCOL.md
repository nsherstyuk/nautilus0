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

### Standard Sections

```markdown
# [Date] Title

## What Was Done
- Bullet list of completed work

## What Was Tried (and failed/changed)
- Important for avoiding repeated mistakes

## Key Decisions & Rationale
- Why we chose X over Y

## Current State
- What's running, what's deployed, current configs

## Next Steps
- Prioritized list
```

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
