# Pitfall notes

Retrospectives, not contracts: what was slow to diagnose and why. A note records
the symptom, the root cause (never visible in the error itself), the fix, and how
to avoid it next time. Changing code does NOT require updating a note.

Naming: `{YYYYMMDD-HHMMSS}-{english-topic}.md`.

| Note | Covers |
|---|---|
| [20260923-122306-t7-frontend-gate-baseline-drift.md](20260923-122306-t7-frontend-gate-baseline-drift.md) | Proving a red frontend gate (ai-studio vitest, i18n parity/deadKeys) is inherited, not yours: the shared-stash-safe baseline check, and happy-dom's missing EventSource. |
