# ruyi-telegram-bot

An independent Telegram notification and human-interaction transport split
from [`ruyisdk-test/riko-bot`](https://github.com/ruyisdk-test/riko-bot).

The service accepts generic HTTP/JSON message requests, renders Telegram
messages and buttons, receives human selections, routes the resulting event to
a configured workflow, and reports callback delivery status to the Telegram
user. It does not interpret the business meaning of an option.

## Architecture

The original Riko responsibilities are being separated into three services:

```text
original riko-bot
   |
   +-- test-bot          test / detection / queries
   +-- package/PR bot    packaging / changes / pull requests
   +-- telegram-bot      notifications / human interaction / result routing
```

AI is a horizontal capability that may participate in any of those workflows.
It is not a fixed central upstream, callback consumer, or router.

```text
workflow/service
    | Human Interaction Request
    v
ruyi-telegram-bot -> Telegram -> human selection
    |
    | Human Interaction Result
    v
configured consuming workflow
```

The request producer, option producer, human decision-maker, and result
consumer may all be different. `callback_target` therefore identifies the
result consumer; it does not identify or default to the requester.

Services communicate through HTTP/JSON. This repository does not import test,
package, Manifest, nvchecker, or PR business code from the other repositories.

## Responsibilities and boundaries

This service provides:

- `GET /health` and `GET /version`;
- `POST /api/v1/messages` for plain text and optional buttons;
- default or per-request Telegram chat IDs;
- HTTP(S) URL buttons;
- dynamic zero-to-N action options, rendered at up to two per row;
- Telegram callback polling and immediate callback acknowledgement;
- logical callback-target routing through controlled configuration;
- legacy single-consumer callback forwarding;
- received, delivered, and failed transport feedback.

It does not provide package/test/PR decisions, AI reasoning, model clients,
workflow task state, option semantics, context restoration, a database, Redis,
a message queue, durable retries, a scheduler, API authentication, or a
free-text Telegram state machine.

The consuming workflow owns all package, failure, patch, PR, prompt, reasoning,
and task context. It restores that context using `interaction_id`.

## Requirements and installation

- Python 3.10 or newer (Python 3.12 is recommended)
- Poetry
- FastAPI, httpx, Pydantic, and `python-telegram-bot`

```bash
poetry install
cp .env.example .env
```

Never commit a real Telegram token, chat ID, proxy credential, or credential-
bearing callback endpoint.

## Configuration

```env
APP_HOST=127.0.0.1
APP_PORT=9878

TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

CALLBACK_TARGETS_JSON={"test-workflow":"http://127.0.0.1:9877/callback","package-pr-workflow":"http://127.0.0.1:9880/callback"}
CALLBACK_FORWARD_URL=

HTTP_PROXY=
HTTPS_PROXY=
```

`TELEGRAM_TOKEN` is required at startup. `TELEGRAM_CHAT_ID` is optional when
every message request supplies `chat_id`.

`CALLBACK_TARGETS_JSON` is an optional JSON object mapping logical target names
to controlled HTTP(S) endpoints. It is parsed at startup; malformed JSON,
blank target names, non-string values, and non-HTTP(S) endpoints fail early.
Callers submit only a logical `callback_target`, never an arbitrary callback
URL. Adding a target changes configuration, not callback-routing code.

`CALLBACK_FORWARD_URL` is the legacy/default single-consumer route:

- a new interaction with an explicit target uses only the registry;
- an unknown explicit target is an error and never falls back;
- a new interaction without a target uses `CALLBACK_FORWARD_URL`;
- a legacy `action` uses `CALLBACK_FORWARD_URL`;
- an action-button request without any usable route returns HTTP 422 before a
  Telegram message is sent.

`HTTPS_PROXY` is preferred for Telegram HTTPS traffic, with `HTTP_PROXY` as a
fallback. Existing environment proxy behavior is otherwise unchanged.

The service listens on `127.0.0.1:9878` by default. Bind another address only
when the deployment requires it.

## Run

```bash
poetry run python -m telegram_bot
```

or:

```bash
poetry run python -m uvicorn telegram_bot.main:app --host 127.0.0.1 --port 9878
```

## Health and version

```bash
curl http://127.0.0.1:9878/health
curl http://127.0.0.1:9878/version
```

```json
{"status":"ok"}
```

```json
{"version":"0.1.0"}
```

## Message API

### Plain text

```json
{
  "text": "Telegram service smoke test"
}
```

A request-specific `chat_id` overrides `TELEGRAM_CHAT_ID`:

```json
{
  "text": "Send to another chat",
  "chat_id": 123456789
}
```

Successful response:

```json
{
  "success": true,
  "chat_id": 123456789,
  "message_id": 456
}
```

Telegram send failures return HTTP 503 with a sanitized error.

### URL buttons

URL-only messages need no interaction fields:

```json
{
  "text": "PR created",
  "buttons": [
    {
      "type": "url",
      "text": "View PR",
      "url": "https://github.com/qingwan12138/ruyi-telegram-bot"
    }
  ]
}
```

URL buttons accept only `http://` and `https://`, and reject `option_id` and
legacy `action` fields.

### Human interaction

New action options require `interaction_id` and use `option_id`. The option
count is dynamic; “Manual review” is just another option with no special logic.
Each `option_id` must be unique within one interaction, but it does not need to
be globally unique and may be reused by another `MessageRequest`.

```json
{
  "text": "Choose an action",
  "interaction_id": "decision-789",
  "callback_target": "package-pr-workflow",
  "buttons": [
    {
      "type": "action",
      "text": "Retry",
      "option_id": "retry"
    },
    {
      "type": "action",
      "text": "Manual review",
      "option_id": "manual"
    }
  ]
}
```

Example result delivered to the configured consuming workflow:

```json
{
  "event": "telegram.interaction.selected",
  "interaction_id": "decision-789",
  "option_id": "manual",
  "option_text": "Manual review",
  "chat_id": 123456789,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

`interaction_id + option_id` is the stable machine protocol. `option_text` is
optional, best-effort display metadata recovered from the Telegram message's
inline keyboard; it may be `null`. Consumers must not use natural-language
`option_text` as the machine action key. The Telegram service never stores the
full AI, test, package, or PR context and never tries to understand what
`manual` or another option means. The consuming workflow stores and restores
that business context using `interaction_id`.

## Callback data protocol

New buttons use a stateless short encoding:

```text
h1|<target-character-count>|<interaction-character-count>|<target><interaction><option>
```

Length prefixes are Unicode character counts. The complete encoded value is
limited separately to 64 UTF-8 bytes, including the prefix and lengths. A new
interaction using `CALLBACK_FORWARD_URL` encodes a target length of zero.
The 64-byte limit applies only to Telegram `callback_data`, not to the callback
HTTP JSON body; `option_text` is never added to `callback_data`.

The decoder safely rejects malformed prefixes, lengths, bounds, empty
interaction/option IDs, and payloads over the byte limit. `h1|` is reserved;
legacy actions may not begin with it. No in-memory callback map is used, so a
service restart does not discard routing context.

## Callback feedback

Long polling is used; no public Telegram webhook is required.

1. Telegram click received: `answerCallbackQuery` displays
   `Selection received.`
2. Result accepted by the target HTTP endpoint: the user receives
   `Selection delivered successfully.`
3. Target returns HTTP 409 for a new `InteractionResult`: the user receives
   `This interaction has already been resolved.`
4. Unknown target, malformed data, or any other non-2xx HTTP response: the user
   receives
   `Failed to deliver your selection.`
5. Timeout, connection error, reset, or other network uncertainty: the user
   receives `Could not confirm delivery of your selection.`

The delivery outcomes are therefore: 2xx = delivered; 409 = already resolved
only for the new `InteractionResult` contract; any other non-2xx HTTP response
and route resolution failures = failed; timeout or network uncertainty =
unknown. For legacy `telegram.action`, HTTP 409 is failed because that event has
no `interaction_id`. Redirect responses such as 301, 302, 307, and 308 are not
followed and are failed. Unknown does not mean the target definitely did not
receive the request: delivery may have completed before the response was lost.

“Received” means Telegram delivered the click to this service. “Delivered”
means the target workflow accepted the HTTP result. Neither message means the
business workflow, AI, test, package update, or PR completed successfully.
After real business completion, that workflow may call
`POST /api/v1/messages` again with its own result message.

Acknowledgement, forwarding, and feedback-send failures are isolated so the
polling loop continues. The service does not automatically retry an unknown
delivery because doing so could repeat a business side effect. There is
intentionally no durable retry queue.

### Consumer idempotency contract

Consuming workflows MUST provide business-level idempotency using
`interaction_id` as the idempotency key. A workflow should normally accept only
one final human decision for each interaction: the first valid selection moves
the interaction from pending to resolved, and later selections for that
interaction return HTTP 409. `callback_query_id` is transport metadata, not the
business idempotency key.

The Telegram Bot does not persist resolved interactions or perform business
deduplication. It has no database, Redis/Valkey state, in-memory resolved map,
or business state machine; those responsibilities remain with the consuming
workflow.

## Legacy action compatibility

Existing callers may continue using an opaque `action` button when
`CALLBACK_FORWARD_URL` is configured:

```json
{
  "text": "Legacy decision",
  "buttons": [
    {
      "type": "action",
      "text": "Continue",
      "action": "task123:continue"
    }
  ]
}
```

The delivered event remains:

```json
{
  "event": "telegram.action",
  "action": "task123:continue",
  "chat_id": 123456789,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

Legacy and new action buttons cannot be mixed in one request. The intentional
contract change is that legacy actions without `CALLBACK_FORWARD_URL` are now
rejected instead of creating buttons that only log selections.

## Validation and safety

- request and model objects reject unknown fields;
- message and identifier strings are trimmed and may not be blank;
- interaction fields are accepted only with new action options;
- callback target existence is checked by the route/service layer against the
  runtime registry, not by the pure Pydantic models;
- callback endpoint URLs, query tokens, Telegram tokens, proxy credentials,
  and exception details are not emitted to logs or user feedback;
- malformed callbacks and delivery failures do not terminate polling.

## Tests

```bash
poetry run pytest -q
python -m compileall telegram_bot tests
```

Unit tests use fakes and `httpx.MockTransport`; they do not require a real
Telegram account. Real smoke tests are run only when usable local
`TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` values are present.

## Relationship to the original Telegram implementation

The project retains the proven environment token/chat configuration,
proxy-aware `python-telegram-bot` client, FastAPI message endpoint, URL buttons,
inline keyboard layout, long polling, safe error logging, and Telegram 503
behavior from the original Riko implementation.

It deliberately does not restore `PackageReportData`, `PackageReportService`,
package enrichment, Manifest/PR fields, scheduler behavior, or persistence.
