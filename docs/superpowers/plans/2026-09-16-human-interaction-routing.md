# Human Interaction Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stateless human-interaction callback encoding, logical target routing, legacy fallback, and received/delivered/failed feedback without adding business logic or durable state.

**Architecture:** Extend the existing Pydantic contract compatibly, isolate callback-data encoding in a small pure module, resolve logical targets from startup configuration in the service layer, and keep Telegram transport mechanics in `TelegramClient`. New interaction callbacks carry all routing identifiers in a length-prefixed payload; legacy actions remain opaque and use only the configured fallback URL.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic 2.x, python-telegram-bot 22.x, httpx, Poetry, pytest, pytest-asyncio

## Global Constraints

- Use `h1|<target-character-count>|<interaction-character-count>|<target><interaction><option>` for new callback data.
- Length prefixes count Unicode characters; the complete callback data is limited to 64 UTF-8 bytes.
- Reject legacy `action` values beginning with reserved prefix `h1|`.
- Encode a new interaction using `CALLBACK_FORWARD_URL` fallback with target character count zero.
- Validate target existence in route/service code against runtime settings, not inside pure Pydantic validation.
- Treat malformed new callback data as a controlled delivery failure; never reinterpret it as legacy.
- Preserve plain text, URL buttons, chat ID override, proxy handling, health/version, lifespan, polling recovery, and Telegram 503 behavior.
- Do not add a database, Redis, queue, scheduler, authentication, business workflow logic, LLM client, or central AI service.
- Do not push, merge, create a PR, or modify a remote branch.

---

## File Map

- Create `telegram_bot/callback_data.py`: pure versioned encoder/decoder and controlled codec errors.
- Modify `telegram_bot/models.py`: compatible button/request models and new interaction result.
- Modify `telegram_bot/config.py`: parse target registry and resolve runtime delivery routes.
- Modify `telegram_bot/telegram_client.py`: encode new buttons and send feedback using existing message transport.
- Modify `telegram_bot/routes.py`: reject unresolved action routes before sending Telegram messages.
- Modify `telegram_bot/callback_service.py`: parse, route, forward, and report delivery status.
- Modify `telegram_bot/main.py`: retain lifecycle wiring with the expanded service.
- Modify `.env.example`, `README.md`, `pyproject.toml`, and historical docs: configuration, architecture, metadata, and history clarification.
- Modify/add tests under `tests/`: model, codec, configuration, routes, keyboard, callbacks, feedback, and regression coverage.

### Task 1: Runtime Target Registry

**Files:**
- Modify: `tests/test_phase1.py`
- Modify: `telegram_bot/config.py`

**Interfaces:**
- Produces: `Settings.callback_targets: dict[str, str]`.
- Produces: `Settings.resolve_callback_url(callback_target: str | None) -> str`.
- Produces: `UnknownCallbackTargetError` and `MissingCallbackRouteError`.

- [ ] **Step 1: Write failing configuration tests**

Add tests that load two targets from `CALLBACK_TARGETS_JSON`, resolve each endpoint, reject malformed JSON/non-object/blank keys/non-string values/non-HTTP(S) URLs, reject an unknown explicit target without fallback, resolve `None` through `CALLBACK_FORWARD_URL`, and fail when neither route exists.

```python
def test_callback_targets_are_loaded_and_resolved() -> None:
    settings = Settings.load({
        "CALLBACK_TARGETS_JSON": (
            '{"target-a":"http://a.local/callback",'
            '"target-b":"https://b.local/callback"}'
        )
    })
    assert settings.resolve_callback_url("target-a") == "http://a.local/callback"
    assert settings.resolve_callback_url("target-b") == "https://b.local/callback"

def test_unknown_explicit_target_never_uses_fallback() -> None:
    settings = Settings(
        callback_forward_url="http://fallback.local/callback",
        callback_targets={"known": "http://known.local/callback"},
    )
    with pytest.raises(UnknownCallbackTargetError):
        settings.resolve_callback_url("missing")
```

- [ ] **Step 2: Run the configuration tests and verify RED**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_phase1.py -q`

Expected: FAIL because registry fields and route resolution do not exist.

- [ ] **Step 3: Implement validated startup parsing and resolution**

Use `json.loads`, require an object of non-blank string keys and string HTTP(S)
URLs with a host, and return the explicit registry entry or the fallback according
to the approved rules. Do not log endpoint values.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_phase1.py -q`

- [ ] **Step 5: Commit**

```powershell
git add telegram_bot/config.py tests/test_phase1.py
git commit -m "feat: add callback target registry"
```

### Task 2: Interaction Models and Stateless Callback Codec

**Files:**
- Create: `telegram_bot/callback_data.py`
- Create: `tests/test_callback_data.py`
- Modify: `telegram_bot/models.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces: `encode_interaction_callback(target, interaction_id, option_id) -> str`.
- Produces: `decode_interaction_callback(data) -> InteractionCallbackData`.
- Produces: `CallbackDataError` and `InteractionCallbackData`.
- Produces: `MessageRequest.interaction_id`, `MessageRequest.callback_target`, `Button.option_id`, and `InteractionResult`.

- [ ] **Step 1: Write failing model tests**

Cover plain text and URL-only requests without interaction fields; one, two, and
four action options; a manual option; required/non-blank interaction and option
IDs; forbidden URL/action field combinations; mixed legacy/new actions; unknown
fields; and the reserved `h1|` legacy prefix.

```python
def test_new_action_request_requires_interaction_id() -> None:
    with pytest.raises(ValidationError, match="interaction_id"):
        MessageRequest(
            text="Choose",
            buttons=[Button(type="action", text="Retry", option_id="retry")],
        )

def test_legacy_action_rejects_reserved_prefix() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        Button(type="action", text="Old", action="h1|legacy")
```

- [ ] **Step 2: Run model tests and verify RED**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_models.py -q`

- [ ] **Step 3: Implement the compatible models**

Keep structural button validation in `Button`, cross-button mode validation in
`MessageRequest`, and no registry lookup in either model. Define new result data
with event `telegram.interaction.selected` while retaining `CallbackEvent` for
legacy delivery.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_models.py -q`

- [ ] **Step 5: Write failing codec tests**

Cover round-trip with delimiters and Unicode, empty target fallback, exactly 64
UTF-8 bytes, more than 64 bytes, a multibyte boundary, invalid prefix, missing
or non-decimal lengths, signs/negative lengths, target and interaction bounds,
empty interaction, empty option, and over-limit inbound data.

```python
def test_unicode_lengths_count_characters_but_limit_counts_bytes() -> None:
    encoded = encode_interaction_callback("目标", "决策", "选项")
    assert encoded.startswith("h1|2|2|")
    assert decode_interaction_callback(encoded).option_id == "选项"

def test_empty_target_round_trips_for_fallback() -> None:
    encoded = encode_interaction_callback(None, "decision-1", "retry")
    assert encoded.startswith("h1|0|10|")
    assert decode_interaction_callback(encoded).callback_target is None
```

- [ ] **Step 6: Run codec tests and verify RED**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_callback_data.py -q`

- [ ] **Step 7: Implement the minimal codec**

Parse exactly two decimal length fields after `h1|`, slice the payload using
Python Unicode character counts, require non-empty interaction and option IDs,
and validate the final UTF-8 byte size in both encoder and decoder.

- [ ] **Step 8: Run focused and combined tests and verify GREEN**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_models.py tests/test_callback_data.py -q`

- [ ] **Step 9: Commit**

```powershell
git add telegram_bot/models.py telegram_bot/callback_data.py tests/test_models.py tests/test_callback_data.py
git commit -m "feat: model human interactions and callback data"
```

### Task 3: Route Validation and Keyboard Encoding

**Files:**
- Modify: `tests/test_routes.py`
- Modify: `tests/test_telegram_client.py`
- Modify: `telegram_bot/routes.py`
- Modify: `telegram_bot/telegram_client.py`

**Interfaces:**
- `TelegramClient.send_message` accepts `interaction_id` and `callback_target`.
- `TelegramClient.build_keyboard` encodes new option buttons and preserves legacy action data.
- `POST /api/v1/messages` validates the runtime delivery route before sending action buttons.

- [ ] **Step 1: Write failing route tests**

Cover known target success, unknown target 422 despite fallback, new fallback
success with no target, no-route rejection for new and legacy actions, arbitrary
`callback_url` rejection, and unchanged plain/URL behavior without routes.

- [ ] **Step 2: Write failing keyboard tests**

Assert new buttons contain decodable interaction data, fallback buttons encode
target length zero, legacy callback data remains unchanged, and layout remains
`[2, 2, 1]` for five buttons.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_routes.py tests/test_telegram_client.py -q`

- [ ] **Step 4: Implement runtime preflight and keyboard encoding**

Resolve the route only when action buttons exist. Pass interaction context to
the client, use the codec only for `option_id`, and preserve URL and legacy
button construction.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_routes.py tests/test_telegram_client.py -q`

- [ ] **Step 6: Commit**

```powershell
git add telegram_bot/routes.py telegram_bot/telegram_client.py tests/test_routes.py tests/test_telegram_client.py
git commit -m "feat: encode and validate interaction buttons"
```

### Task 4: Callback Routing and Delivery Feedback

**Files:**
- Modify: `tests/test_callbacks.py`
- Modify: `tests/test_polling.py`
- Modify: `telegram_bot/callback_service.py`

**Interfaces:**
- New callbacks deliver `InteractionResult` to the decoded logical target.
- Legacy callbacks deliver `CallbackEvent` to `CALLBACK_FORWARD_URL`.
- Feedback constants are exactly `Selection received.`, `Selection delivered successfully.`, and `Failed to deliver your selection.`.

- [ ] **Step 1: Expand callback fakes and write failing success tests**

Capture acknowledgement, HTTP forwarding, and feedback-message order. Assert
new interaction parsing, all Telegram metadata, target A/B routing, empty-target
fallback, legacy event compatibility, and success feedback.

- [ ] **Step 2: Write failing failure-path tests**

Cover 4xx, 5xx, timeout, network failure, unknown target, malformed payload,
acknowledgement failure with continued delivery, feedback-send failure, secret
URL redaction, and handler non-propagation so polling remains alive.

- [ ] **Step 3: Run callback/polling tests and verify RED**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_callbacks.py tests/test_polling.py -q`

- [ ] **Step 4: Implement parsing, routing, forwarding, and feedback**

Always attempt acknowledgement first. Build the appropriate event, resolve the
route, POST JSON and call `raise_for_status`. Catch controlled route/codec and
HTTP failures, log only safe type/status/target information, then best-effort
send the exact success or failure text to the callback chat.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_callbacks.py tests/test_polling.py -q`

- [ ] **Step 6: Commit**

```powershell
git add telegram_bot/callback_service.py tests/test_callbacks.py tests/test_polling.py
git commit -m "feat: route interaction callbacks with feedback"
```

### Task 5: Architecture Documentation and Package Metadata

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Modify: `docs/superpowers/specs/2026-09-16-ai-decision-feedback-design.md`
- Modify: `docs/superpowers/plans/2026-09-16-ai-decision-feedback.md`
- Modify: `docs/superpowers/plans/2026-09-16-local-environment-hygiene.md`
- Modify: `poetry.lock` only if Poetry metadata refresh changes it.

**Interfaces:**
- Documents the three-service split, horizontal AI role, public JSON contracts, routing configuration, transport-only feedback, and legacy fallback.
- Package name is `ruyi-telegram-bot`; license metadata is Apache-2.0.

- [ ] **Step 1: Rewrite README architecture and examples**

Document dynamic zero-to-N options, manual review, `interaction_id`, `option_id`,
logical `callback_target`, requester/consumer distinction, workflow-owned
context, exact feedback meanings, malformed behavior, and legacy contract.

- [ ] **Step 2: Update environment and metadata**

Add an empty documented `CALLBACK_TARGETS_JSON=` entry. Change Poetry name to
`ruyi-telegram-bot` and add `license = "Apache-2.0"` using current Poetry
metadata syntax.

- [ ] **Step 3: Mark prior design/plan files as historical/completed**

Add a clear historical note to the former fixed-AI/fixed-upstream documents and
convert completed execution checkboxes from `[ ]` to `[x]` so they no longer
look pending. Do not rewrite history to claim they designed the new registry.

- [ ] **Step 4: Refresh and validate Poetry metadata**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pip install 'poetry==2.4.3'
& '.venv\Scripts\python.exe' -m poetry lock
& '.venv\Scripts\python.exe' -m poetry check --lock
```

Expected: Poetry uses the same version recorded in the lock-file header, the
lock content hash reflects `pyproject.toml`, and `check --lock` exits zero.

- [ ] **Step 5: Commit**

```powershell
git add README.md .env.example pyproject.toml poetry.lock docs/superpowers
git commit -m "docs: describe generic interaction routing"
```

### Task 6: Full Phase 7 Verification and Acceptance Audit

**Files:**
- Verify all changed files; modify only if a failing verification exposes a defect, and add a regression test before fixing code.

**Interfaces:**
- Produces evidence for every acceptance item and the section 44 final report.

- [ ] **Step 1: Install/check the locked environment**

Run:

```powershell
& '.venv\Scripts\python.exe' -m poetry install
```

Expected: exit code zero using the committed lock file.

- [ ] **Step 2: Run the full suite**

Run: `.venv\\Scripts\\python.exe -m pytest -q`

- [ ] **Step 3: Compile source and tests**

Run: `.venv\\Scripts\\python.exe -m compileall -q telegram_bot tests`

- [ ] **Step 4: Validate metadata and diff**

Run:

```powershell
& '.venv\Scripts\python.exe' -m poetry check --lock
git diff --check
git status --short
git diff --stat daa0114..HEAD
```

Then inspect the complete local diff against the approved design.

- [ ] **Step 5: Scan for forbidden capabilities and exposed secrets**

Use targeted `rg` searches for forbidden infrastructure/client terms and known
secret patterns. Distinguish documentation statements saying a feature is not
present from actual implementation references.

- [ ] **Step 6: Decide real Telegram smoke tests from credentials**

Check only whether usable `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` are available,
without printing them. Run Tests A-E only when safe usable credentials exist;
otherwise record each as `NOT RUN`.

- [ ] **Step 7: Commit any verification-only fixes**

Only if required, add the regression test and minimal fix in a separate commit.
Do not push or merge.

- [ ] **Step 8: Report exactly in task document section 44 format**

Report Design, Modified files, Backward compatibility, actual test count, real
Telegram A-E status, and remaining issues.
