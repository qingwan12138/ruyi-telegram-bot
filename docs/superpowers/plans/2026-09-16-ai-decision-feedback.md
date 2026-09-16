# AI Decision Callback Feedback Implementation Plan

> Historical completed plan: this implemented the earlier single-consumer
> acknowledgement stage. It is retained as execution history, not as the
> current architecture. See `2026-09-16-human-interaction-routing.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an immediate generic `Selection received.` Telegram acknowledgement for AI decision button clicks while preserving generic asynchronous callback forwarding and documenting how the upstream AI later reports its result.

**Architecture:** Extend the Telegram transport wrapper so callback acknowledgements may carry optional text, then have `CallbackService` supply one fixed generic acknowledgement before validating or forwarding a callback. Keep the existing HTTP contracts unchanged; the upstream service continues to interpret opaque actions and posts later results through `POST /api/v1/messages`.

**Tech Stack:** Python 3.10+, FastAPI, python-telegram-bot 22.x, httpx, Pydantic 2.x, pytest, pytest-asyncio

## Global Constraints

- Do not add an AI/model client, AI credentials, prompts, task storage, or AI-specific routes.
- Do not change the `MessageRequest` or `CallbackEvent` JSON contracts.
- The acknowledgement text is exactly `Selection received.` and is not configurable in this change.
- Acknowledgement remains best-effort and must not block callback forwarding when it fails.
- Callback forwarding remains best-effort with no database, durable retry, queue, or message broker.
- Do not inspect keyboard labels, expose opaque action values in the acknowledgement, edit the original message, or remove its buttons.
- Preserve all existing tests and secret-sanitized logging behavior.

---

## File Map

- Modify `telegram_bot/telegram_client.py`: allow callback acknowledgements to carry optional text.
- Modify `telegram_bot/callback_service.py`: define and send the fixed generic acknowledgement.
- Modify `tests/test_telegram_client.py`: verify the Telegram Bot API receives the acknowledgement text.
- Modify `tests/test_callbacks.py`: verify callback-service feedback, failure isolation, malformed callbacks, forwarding order, and unchanged event data.
- Modify `README.md`: document the two-stage AI decision and result-feedback flow.

### Task 1: Pass Optional Text to Telegram Callback Acknowledgements

**Files:**
- Modify: `tests/test_telegram_client.py`
- Modify: `telegram_bot/telegram_client.py:75-81`

**Interfaces:**
- Consumes: `TelegramClient` initialized with a `telegram.Bot`-compatible object.
- Produces: `TelegramClient.answer_callback_query(callback_query_id: str, *, text: str | None = None) -> None`.

- [x] **Step 1: Write the failing transport test**

Add this test to `tests/test_telegram_client.py`:

```python
@pytest.mark.asyncio
async def test_answer_callback_query_passes_feedback_text() -> None:
    class CallbackBot:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def answer_callback_query(self, **kwargs) -> None:
            self.calls.append(kwargs)

    bot = CallbackBot()
    client = TelegramClient(Settings(telegram_token="x"), bot=bot)

    await client.answer_callback_query(
        "callback-1",
        text="Selection received.",
    )

    assert bot.calls == [
        {
            "callback_query_id": "callback-1",
            "text": "Selection received.",
        }
    ]
```

- [x] **Step 2: Run the new test and verify the signature fails**

Run:

```bash
poetry run pytest tests/test_telegram_client.py::test_answer_callback_query_passes_feedback_text -q
```

Expected: FAIL with `TypeError` because `answer_callback_query` does not yet accept `text`.

- [x] **Step 3: Implement the minimal optional-text transport**

Replace `TelegramClient.answer_callback_query` in `telegram_bot/telegram_client.py` with:

```python
async def answer_callback_query(
    self,
    callback_query_id: str,
    *,
    text: str | None = None,
) -> None:
    """Acknowledge a Telegram inline-button callback."""
    kwargs: dict[str, str] = {"callback_query_id": callback_query_id}
    if text is not None:
        kwargs["text"] = text

    try:
        await self.bot.answer_callback_query(**kwargs)
    except Exception as exc:
        logger.error("Telegram callback acknowledgement failed (%s)", type(exc).__name__)
        raise TelegramCallbackError("Telegram callback acknowledgement failed") from None
```

- [x] **Step 4: Run the focused Telegram client tests**

Run:

```bash
poetry run pytest tests/test_telegram_client.py -q
```

Expected: all tests in `tests/test_telegram_client.py` pass.

- [x] **Step 5: Commit the transport change**

```bash
git add telegram_bot/telegram_client.py tests/test_telegram_client.py
git commit -m "feat: support callback acknowledgement text"
```

### Task 2: Send Fixed Feedback Before Forwarding AI Decisions

**Files:**
- Modify: `tests/test_callbacks.py`
- Modify: `telegram_bot/callback_service.py:14-37`

**Interfaces:**
- Consumes: `TelegramClient.answer_callback_query(callback_query_id: str, *, text: str | None = None)` from Task 1.
- Produces: module constant `CALLBACK_ACK_TEXT = "Selection received."` and callback handling that supplies it before parsing or forwarding.

- [x] **Step 1: Extend the callback fake to capture acknowledgement text**

Update `FakeTelegramClient` in `tests/test_callbacks.py` to preserve the existing ID assertions and separately capture text:

```python
class FakeTelegramClient:
    def __init__(
        self,
        *,
        answer_error: Exception | None = None,
        trace: list[str] | None = None,
    ) -> None:
        self.answered: list[str] = []
        self.answer_texts: list[str | None] = []
        self.answer_error = answer_error
        self.trace = trace

    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
    ) -> None:
        self.answered.append(callback_query_id)
        self.answer_texts.append(text)
        if self.trace is not None:
            self.trace.append("acknowledge")
        if self.answer_error:
            raise self.answer_error
```

- [x] **Step 2: Write failing tests for feedback, ordering, and malformed callbacks**

In `test_callback_is_answered_and_parsed_without_forward_url`, add:

```python
assert telegram.answer_texts == ["Selection received."]
```

Add these tests to `tests/test_callbacks.py`:

```python
@pytest.mark.asyncio
async def test_callback_is_acknowledged_before_forwarding() -> None:
    trace: list[str] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        trace.append("forward")
        return httpx.Response(204)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    service = CallbackService(
        Settings(callback_forward_url="http://upstream.local/callback"),
        FakeTelegramClient(trace=trace),
        http_client,
    )

    try:
        await service.handle(make_query())
    finally:
        await http_client.aclose()

    assert trace == ["acknowledge", "forward"]


@pytest.mark.asyncio
async def test_incomplete_callback_is_acknowledged_but_not_forwarded() -> None:
    forwarded = False

    async def receiver(request: httpx.Request) -> httpx.Response:
        nonlocal forwarded
        forwarded = True
        return httpx.Response(204)

    query = make_query()
    query.message = None
    telegram = FakeTelegramClient()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    service = CallbackService(
        Settings(callback_forward_url="http://upstream.local/callback"),
        telegram,
        http_client,
    )

    try:
        event = await service.handle(query)
    finally:
        await http_client.aclose()

    assert event is None
    assert telegram.answered == ["callback-1"]
    assert telegram.answer_texts == ["Selection received."]
    assert forwarded is False
```

- [x] **Step 3: Run the callback tests and verify the feedback assertions fail**

Run:

```bash
poetry run pytest tests/test_callbacks.py -q
```

Expected: feedback assertions fail because `CallbackService` currently calls the client without text.

- [x] **Step 4: Implement the fixed generic acknowledgement**

Add this constant below the logger in `telegram_bot/callback_service.py`:

```python
CALLBACK_ACK_TEXT = "Selection received."
```

Change the first call inside `CallbackService.handle` to:

```python
await self.telegram_client.answer_callback_query(
    query.id,
    text=CALLBACK_ACK_TEXT,
)
```

Do not move this call below callback parsing or forwarding.

- [x] **Step 5: Run the complete callback tests**

Run:

```bash
poetry run pytest tests/test_callbacks.py -q
```

Expected: all callback tests pass, including existing acknowledgement-failure and forwarding-failure coverage.

- [x] **Step 6: Commit the callback-service change**

```bash
git add telegram_bot/callback_service.py tests/test_callbacks.py
git commit -m "feat: acknowledge AI decision selections"
```

### Task 3: Document the Two-Stage AI Feedback Flow

**Files:**
- Modify: `README.md` near `## Callback handling` and `## AI boundary`

**Interfaces:**
- Consumes: unchanged `POST /api/v1/messages` and `CallbackEvent` contracts.
- Produces: user-facing documentation distinguishing immediate receipt from later upstream completion.

- [x] **Step 1: Update callback acknowledgement documentation**

In the callback-handling sequence, describe the first step as:

```markdown
1. receives the Telegram `callback_query`;
2. immediately calls `answerCallbackQuery` with `Selection received.`;
3. builds a generic callback event;
4. forwards it to `CALLBACK_FORWARD_URL` when configured;
5. otherwise logs the event and finishes.
```

Add this clarification immediately after the sequence:

```markdown
The acknowledgement only confirms that this service received the click. It does not mean that an upstream AI or task runner has completed the selected action.
```

- [x] **Step 2: Add an AI decision feedback example**

Add a subsection under `## AI boundary` containing:

````markdown
### AI decision feedback

An upstream AI service can send decision options using ordinary action buttons. The action should contain a short upstream task identifier, for example `task123:choose_a`.

After the user clicks an option, this service immediately displays `Selection received.` and forwards the generic callback event. The upstream service uses the action to restore its own task context and process the decision.

When processing finishes, the upstream service reports the result by calling the existing message endpoint again, using the `chat_id` from the callback event:

```json
{
  "chat_id": 123456789,
  "text": "Solution A completed successfully."
}
```

This repository does not call an AI model, store AI task state, or wait synchronously for AI execution.
````

- [x] **Step 3: Check documentation terminology and formatting**

Run:

```bash
rg -n "Selection received|AI decision feedback|synchronously" README.md
```

Expected: matches appear in callback handling and the AI decision subsection, and no statement implies that acknowledgement means execution success.

- [x] **Step 4: Commit the documentation change**

```bash
git add README.md
git commit -m "docs: explain asynchronous AI decision feedback"
```

### Task 4: Full Verification

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: all changes from Tasks 1-3.
- Produces: evidence that the repository remains syntactically valid, tests pass, contracts remain generic, and no secret was added.

- [x] **Step 1: Run the full automated test suite**

Run:

```bash
poetry run pytest -q
```

Expected: all tests pass with the exact count reported from the command; do not predict or invent the count.

- [x] **Step 2: Compile source and tests**

Run:

```bash
poetry run python -m compileall -q telegram_bot tests
```

Expected: exit code 0 with no syntax errors.

- [x] **Step 3: Check that no AI-specific coupling was introduced**

Run:

```bash
rg -n "OpenAI|Claude|API_KEY|/ai|/agent|PackageReport|Manifest|Redis|Valkey|Celery" telegram_bot tests
```

Expected: no new AI client, business model, database, queue, or AI-specific endpoint references.

- [x] **Step 4: Check for accidental secrets and diff problems**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the intended implementation and documentation state is present.

- [x] **Step 5: Perform final review against the design**

Confirm all of the following from the code and test output:

```text
[ ] Clicking an action receives the fixed immediate acknowledgement.
[ ] Acknowledgement failure does not block forwarding.
[ ] CallbackEvent JSON is unchanged.
[ ] Incomplete callbacks are not forwarded.
[ ] Upstream result feedback still uses POST /api/v1/messages.
[ ] No AI client or task state was added.
```

No additional commit is needed unless verification reveals and fixes a defect.
