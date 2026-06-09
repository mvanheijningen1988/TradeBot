---
mode: agent
model: GPT-5.3-Codex
description: Validate commit quality, tests, and documentation before opening a PR.
---

Run a pre-PR quality check on the current branch.

Checklist:
1. Check git status and modified files.
2. Assess whether commit messages clearly describe the real changes.
3. Verify that relevant tests exist and run them.
4. Verify whether `CHANGELOG.md` was updated when needed.
5. Verify whether `README.md` was updated when needed.
6. Provide a Go/No-Go recommendation for a PR to `development`.

Output format:
- Status: `GO` of `NO-GO`
- Findings
- Missing actions
- Recommended commit message(s) if improvement is needed

Rules:
- Be strict on documentation and commit quality.
- Provide concrete file references for missing updates.
