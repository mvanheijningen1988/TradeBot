---
mode: agent
model: GPT-5.3-Codex
description: Create a pull request from a feature branch to development following project rules.
---

Create a pull request from the current feature branch to `development` following the rules in [developer.instructions.md](../instructions/developer.instructions.md).
Validate commit messages against [commit-conventions.md](../commit-conventions.md).

Input:
- PR title: `${input:pr_title}`

Required checks for PR creation:
1. Confirm that the source branch is a feature branch.
2. Confirm target branch = `development`.
3. Verify that commit messages follow Conventional Commits from [commit-conventions.md](../commit-conventions.md):
	- Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`
	- Required format: `type(scope): description`
4. Verify that commit messages are specific and reflect the actual changes.
5. Verify whether `CHANGELOG.md` was updated when the change is relevant.
6. Verify whether `README.md` was updated when behavior/config/setup/API/workflow changed.
7. Run relevant tests for modified component(s) and report the results.
8. Generate the PR summary automatically from commit history and effective code changes; do not ask the user to write it manually.

PR body structure:
- Summary
- What changed
- Why
- Test results
- Documentation updates (`README.md`, `CHANGELOG.md`)
- Risks / attention points

Rules:
- PR must be from feature branch -> `development`.
- No direct PR to `main` for feature work.
- If commit messages do not follow Conventional Commits: stop and provide corrected message suggestions.
- If required checks are missing: stop and show a concrete todo list.
- PR summary must be produced by the agent that creates/validates commits, based on the commit and diff context.
