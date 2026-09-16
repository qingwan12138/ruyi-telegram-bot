# Local Environment Hygiene Design

## Goal

Strengthen local secret and tooling-file protection while keeping the repository's reproducible and reviewable artifacts tracked.

## `.gitignore` Design

The ignore file will be organized by responsibility:

- ignore `.env` and all `.env.*` variants;
- explicitly keep `.env.example` tracked;
- ignore `.venv/` and `venv/` virtual environments;
- retain the existing `.worktrees/` protection;
- ignore Python bytecode, pytest, type-checker, linter, and coverage caches;
- ignore Python build outputs;
- ignore common IDE and operating-system metadata.

The following repository artifacts must remain trackable and must not be copied from `riko-bot`'s ignore rules:

- `poetry.lock`;
- `tests/`;
- `docs/`.

Old `riko-bot` paths such as `cache/`, `config/config.toml`, and `config/nvchecker_keyfile.toml` will not be added because this service does not own those responsibilities.

## `.env.example` Design

The environment template keeps exactly the variables consumed by `telegram_bot.config.Settings`:

- `APP_HOST` and `APP_PORT`;
- required `TELEGRAM_TOKEN`;
- optional `TELEGRAM_CHAT_ID`;
- optional `CALLBACK_FORWARD_URL`;
- optional `HTTP_PROXY` and `HTTPS_PROXY`.

Comments will explain required versus optional values and state that `HTTPS_PROXY` has priority for Telegram HTTPS traffic. Values remain empty where secrets or deployment-specific identifiers are expected. No GitHub, database, package-index, scheduler, or AI variables will be added.

## Verification

Verification will use `git check-ignore` to prove that:

- `.env`, `.env.local`, and `.env.production` are ignored;
- `.env.example` is not ignored;
- `.venv/`, `venv/`, `.worktrees/`, Python caches, IDE metadata, and OS metadata are ignored;
- `poetry.lock`, `tests/`, and `docs/` are not ignored.

The existing Python test suite will also be run to confirm that documentation and ignore-rule changes did not affect application behavior.
