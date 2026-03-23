# 2026-03-22 Documentation Reorganization — Please Read Before Writing Any Files

## Context
We reorganized all 77 .md files in the repo. This message tells you where everything lives now so you don't put files in the wrong place.

## What Changed

### Root is clean — only 2 files allowed
- `README.md` — project readme
- `CODEBASE.md` — agent onboarding guide
- **Nothing else goes in root.** No SESSION_HANDOVER, no RESPONSE_TO, no investigation docs.

### Moved files

| Old Location | New Location |
|-------------|-------------|
| `SESSION_HANDOVER_2026-03-11_1910.md` (root) | `docs/journal/2026-03-11_session-handover-1910.md` |
| `SESSION_HANDOVER_2026-03-12_*.md` (3 files, root) | `docs/journal/2026-03-12_session-handover-*.md` |
| `SESSION_HANDOVER_2026-03-13_1110.md` (root) | `docs/journal/2026-03-13_session-handover-1110.md` |
| `SESSION_HANDOVER_2026-03-16_*.md` (2 files, root) | `docs/journal/2026-03-16_session-handover-*.md` |
| `SESSION_HANDOVER_2026-03-22*.md` (2 files, root) | `docs/journal/2026-03-22_session-handover*.md` |
| `RESPONSE_TO_OTHER_AGENT.md` (root) | `docs/agent-comms/cascade-to-claude/2026-03-22_response-to-multi-pair-findings.md` |
| `RESPONSE_TO_WINDSURF.md` (root) | `docs/agent-comms/claude-to-cascade/2026-03-22_v6-be-walkforward-rebuttal.md` |
| `V7_CODE_REVIEW_2026-03-12.md` (root) | `docs/agent-comms/claude-to-cascade/2026-03-12_v7-code-review.md` |
| `VERIFICATION_DOCUMENT.md` (root) | `docs/research/verification-document.md` |
| `investigation_findings.md` (root) | `docs/research/investigation-findings-multi-pair.md` |
| 20 dead v2/v3 design docs | `docs/archive/design-v2-v3/` |
| 5 dead v2 reference docs | `docs/archive/reference-v2/` |

### Current folder structure

```
docs/
├── COLLABORATION_PROTOCOL.md    ← READ THIS — the full rulebook
├── PROGRESS.md                  ← shared progress tracker (BOTH agents update)
├── DOWNLOADING_TICK_DATA.md     ← reference
├── agent-comms/
│   ├── cascade-to-claude/       ← messages FROM Cascade TO you
│   └── claude-to-cascade/       ← messages FROM you TO Cascade
├── journal/                     ← session journals (BOTH agents write here)
├── research/                    ← research findings & verification docs
├── design/                      ← ONLY current design docs (2 files remain)
│   ├── development_guidelines.md
│   └── project_overview.md
├── reference/                   ← ONLY evergreen reference docs
│   └── ousterhout_design_principles.md
├── standards/                   ← agent guidelines (unchanged)
│   ├── layer1-research-standards.md
│   ├── operating-principles-guide-for-agents.md
│   └── test-creation-guide-for-agents.md
└── archive/                     ← dead v2/v3 docs (preserved, don't touch)
    ├── design-v2-v3/            ← 20 files
    └── reference-v2/            ← 5 files
```

## Rules for You (Claude)

1. **Journal entries:** Write `docs/journal/YYYY-MM-DD_short-description.md` for every session. Use the template in `docs/COLLABORATION_PROTOCOL.md`.

2. **Messages to Cascade:** Write in `docs/agent-comms/claude-to-cascade/YYYY-MM-DD_subject.md`.

3. **Research results:** Write in `docs/research/`. Name descriptively.

4. **PROGRESS.md:** Update `docs/PROGRESS.md` at the end of every session. Update the sections you touched (Research Queue, Completed Research, Parameter History).

5. **Never create files in repo root.** Everything goes under `docs/` or in strategy folders.

6. **Strategy ARCHITECTURE.md files** stay in their strategy folders (e.g., `v8_confirmed_rebreak/ARCHITECTURE.md`). Update them in-place.

7. **Don't touch `docs/archive/`** — those are dead v2/v3 docs preserved for history.

8. **Commit and push** before ending any session.

## Action Items
- [ ] Read `docs/COLLABORATION_PROTOCOL.md` and confirm you agree (or propose changes)
- [ ] Follow these conventions in all future sessions
- [ ] Update `docs/PROGRESS.md` when you complete research tasks
