# Project rules

## Commits go straight to main (operator, 2026-10-19)

Until the operator says otherwise, commit directly to `main` and push it. The code is still raw: no pull requests, no feature
branches, no review step.

- This replaces the "new branch from origin/main, pull request, merge" steps of a goal's definition of done, and any instruction
  that says "never commit to main". The operator's rule wins until it is withdrawn.
- It is about where commits go. Tests, versioning (SemVer in `pyproject.toml`, DEC-023), the statuses of the specification and
  `tasks/` notes are unchanged.
- When the operator withdraws the rule (for example "branches and pull requests again"), delete this section.

## CI is switched off (operator, 2026-10-19)

Until the operator says otherwise, do not wait for CI or fix its checks. The `CI` workflow was disabled on GitHub with
`gh workflow disable CI`; nothing in the repository changed, so the file `.github/workflows/ci.yml` is as it was. The workflow
`diag-linux-chart` was left as it is.

- Run the tests locally before pushing (`.venv/bin/python -m pytest -q -rs`, no test may be skipped) and keep `main` working.
- To switch CI on again: `gh workflow enable CI`, and delete this section.
