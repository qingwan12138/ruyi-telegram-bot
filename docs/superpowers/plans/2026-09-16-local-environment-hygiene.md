# Local Environment Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect common local secret and tooling files while keeping the repository's template, lock file, tests, and documentation trackable.

**Architecture:** Update only the root `.gitignore` and `.env.example`. Verify ignore behavior directly with `git check-ignore`, then run the existing Python suite to prove application behavior remains unchanged.

**Tech Stack:** Git ignore patterns, python-dotenv-compatible environment template, Poetry, pytest

## Global Constraints

- Keep `poetry.lock`, `tests/`, `docs/`, and `.env.example` trackable.
- Do not add old `riko-bot` GitHub, database, package-index, scheduler, or AI variables.
- Keep secret and deployment-specific example values empty.
- State that `TELEGRAM_TOKEN` is required and `HTTPS_PROXY` has priority.
- Do not modify application code or runtime contracts.

---

### Task 1: Harden Local Environment Files

**Files:**
- Modify: `.gitignore`
- Modify: `.env.example`

**Interfaces:**
- Consumes: Git's ignore-pattern semantics and the variables loaded by `telegram_bot.config.Settings`.
- Produces: safe local-file exclusions and a documented environment template with the same variable names and values.

- [ ] **Step 1: Record the failing ignore-rule baseline**

Run:

```powershell
@('.env.local', '.env.production', 'venv/test', '.mypy_cache/test', '.ruff_cache/test', '.idea/workspace.xml', '.vscode/settings.json', '.DS_Store', 'Thumbs.db') | ForEach-Object {
    $match = git check-ignore -v -- $_ 2>$null
    if ($match) { $match } else { "NOT IGNORED`t$_" }
}
```

Expected: every listed path reports `NOT IGNORED`, proving the protection is currently absent.

- [ ] **Step 2: Replace `.gitignore` with the approved grouped rules**

Set `.gitignore` to:

```gitignore
# Environment and secrets
.env
.env.*
!.env.example

# Virtual environments
.venv/
venv/

# Local worktrees
.worktrees/

# Python caches
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Coverage
.coverage
coverage.xml
htmlcov/

# Build artifacts
dist/
build/
*.egg-info/

# IDE and OS files
.idea/
.vscode/
.DS_Store
Thumbs.db
```

- [ ] **Step 3: Add precise comments to `.env.example`**

Set `.env.example` to:

```dotenv
# Application
APP_HOST=127.0.0.1
APP_PORT=9878

# Telegram
# Required at service startup.
TELEGRAM_TOKEN=

# Optional when every message request supplies chat_id.
TELEGRAM_CHAT_ID=

# Optional destination for generic Telegram action events.
CALLBACK_FORWARD_URL=

# Optional proxy settings.
# HTTPS_PROXY is preferred for Telegram HTTPS traffic.
HTTP_PROXY=
HTTPS_PROXY=
```

- [ ] **Step 4: Verify the new positive ignore behavior**

Run:

```powershell
@('.env', '.env.local', '.env.production', '.venv/test', 'venv/test', '.worktrees/test', '__pycache__/x.pyc', '.pytest_cache/test', '.mypy_cache/test', '.ruff_cache/test', '.idea/workspace.xml', '.vscode/settings.json', '.DS_Store', 'Thumbs.db') | ForEach-Object {
    git check-ignore -q -- $_
    if ($LASTEXITCODE -ne 0) { throw "Expected ignored path: $_" }
}
```

Expected: exit code 0 and no exception.

- [ ] **Step 5: Verify important repository artifacts remain trackable**

Run:

```powershell
@('.env.example', 'poetry.lock', 'tests/probe.py', 'docs/probe.md') | ForEach-Object {
    git check-ignore -q --no-index -- $_
    if ($LASTEXITCODE -eq 0) { throw "Expected trackable path: $_" }
}
```

Expected: exit code 0 and no exception from the wrapper; none of the four paths is ignored.

- [ ] **Step 6: Run repository validation**

Run:

```powershell
poetry check --lock
poetry run pytest -p no:cacheprovider -q
git diff --check
```

Expected: the lock file is valid, all tests pass with the actual reported count, and no whitespace errors are reported.

- [ ] **Step 7: Commit the configuration change**

```powershell
git add .gitignore .env.example
git commit -m "chore: harden local environment files"
```
