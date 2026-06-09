---
mode: agent
model: GPT-5.3-Codex
description: Create a feature branch from development using a provided name.
---

Create a new feature branch based on `development`.

Input:
- Desired branch name: `${input:branch_name}`

Tasks:
1. Fetch the latest refs and check out `development`.
2. Pull the latest remote changes for `development`.
3. Create a new branch named `feature/${input:branch_name}`.
4. Return the exact git commands that were executed and the active branch.

Rules:
- Do not use destructive git commands.
- If the branch already exists: stop and provide safe next steps.
- Use only branch names with lowercase letters, numbers, and `-`.
- Briefly report why a step fails if it happens.
