# ruyi-telegram-bot-python

An independent Telegram notification and human-interaction service split from `ruyisdk-test/riko-bot`.

The service is intentionally small. Upstream systems decide **what is important enough to notify**; this repository only accepts a generic message, sends it to Telegram, receives action-button callbacks, and can forward those callbacks to another HTTP service.

## Why this repository exists

The original `riko-bot` contains package/version checks, Manifest generation, PR creation, scheduling, persistence, Telegram integration, and other Ruyi packaging logic. The Telegram path has already proven that FastAPI -> Telegram API -> Telegram message works, but the Telegram responsibility is now being split into its own service.

This repository keeps the useful Telegram integration ideas while removing Riko-specific business coupling.

## Responsibilities

This service is responsible for:

- `GET /health` and `GET /version`;
- receiving generic notification text over HTTP;
- sending plain-text Telegram messages;
- using a configured default chat ID or a request-specific override;
- rendering URL buttons;
- rendering action/decision buttons;
- receiving Telegram `callback_query` updates through long polling;
- acknowledging callbacks with `answerCallbackQuery`;
- optionally forwarding a generic callback event to `CALLBACK_FORWARD_URL`.

It is **not** responsible for:

- package or version checks;
- deciding which failures are important;
- polling `ruyi-index-test-bot` failures;
- Manifest generation;
- nvchecker;
- PR or Issue creation;
- package categories, combos, policies, or version enrichment;
- scheduler logic;
- database/cache/Redis/Valkey/Celery/message queues;
- AI/LLM inference.

The AI/upstream service is expected to decide what to tell a human. Raw batches of test failures should not be pushed directly by this service.

## System relationship

```text
+---------------------+
| ruyi-index-test-bot |
+----------+----------+
           |
           | test / package data
           v
+---------------------+
| AI / processor      |
| (separate project)  |
+----------+----------+
           |
           | important result / decision request
           v
+---------------------+
| ruyi-telegram-bot   |
|  Python + FastAPI   |
+----------+----------+
           |
           v
       Telegram
           |
           | action button
           v
+---------------------+
| callback forwarding |
+----------+----------+
           |
           v
      AI / upstream
```

`ruyi-telegram-bot-python` does not import Python or Go packages from `riko-bot` or `ruyi-index-test-bot`. Services communicate through HTTP/JSON boundaries.

## Requirements

- Python >= 3.10
- Poetry
- FastAPI
- Uvicorn
- `python-telegram-bot`
- httpx

## Install

```bash
poetry install
```

Copy the example environment file and fill in your own values:

```bash
cp .env.example .env
```

Never commit a real Telegram token or chat ID.

## Configuration

```env
APP_HOST=127.0.0.1
APP_PORT=9878

TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

CALLBACK_FORWARD_URL=

HTTP_PROXY=
HTTPS_PROXY=
```

`TELEGRAM_TOKEN` is required at service startup.

`TELEGRAM_CHAT_ID` is optional. If it is empty, each `POST /api/v1/messages` request must provide `chat_id`.

`HTTPS_PROXY` is preferred for Telegram HTTPS traffic, with `HTTP_PROXY` as a fallback. Proxy URLs and the Telegram token are never logged by this service.

`CALLBACK_FORWARD_URL` is optional. When it is empty, action callbacks are acknowledged and logged but are not sent anywhere else.

The default listen address is `127.0.0.1:9878`, avoiding the local ports currently used by the independently split test service. Host and port are configurable.

## Run

Using the configured `APP_HOST` and `APP_PORT`:

```bash
poetry run python -m telegram_bot
```

Or run Uvicorn directly with the documented default address:

```bash
poetry run python -m uvicorn telegram_bot.main:app --host 127.0.0.1 --port 9878 --reload
```

For container or remote access, explicitly configure/bind `0.0.0.0` only when needed.

## Health and version

```bash
curl http://127.0.0.1:9878/health
curl http://127.0.0.1:9878/version
```

Expected responses:

```json
{"status":"ok"}
```

```json
{"version":"0.1.0"}
```

## Send a plain-text message

```bash
curl -X POST http://127.0.0.1:9878/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Telegram service smoke test"
  }'
```

Successful response:

```json
{
  "success": true,
  "chat_id": 123456789,
  "message_id": 456
}
```

A request-specific `chat_id` overrides `TELEGRAM_CHAT_ID`:

```bash
curl -X POST http://127.0.0.1:9878/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Send to another configured target",
    "chat_id": 123456789
  }'
```

If Telegram delivery fails, the API returns HTTP `503` with:

```json
{"detail":"Telegram notification failed"}
```

## URL button

```bash
curl -X POST http://127.0.0.1:9878/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "AI created a pull request.",
    "buttons": [
      {
        "type": "url",
        "text": "View PR",
        "url": "https://github.com/ruyisdk-test/riko-bot"
      }
    ]
  }'
```

V1 URL buttons only accept `http://` or `https://` URLs.

## Action/decision buttons

```bash
curl -X POST http://127.0.0.1:9878/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "AI requires a decision.",
    "buttons": [
      {
        "type": "action",
        "text": "Solution A",
        "action": "demo:solution_a"
      },
      {
        "type": "action",
        "text": "Solution B",
        "action": "demo:solution_b"
      }
    ]
  }'
```

`action` becomes Telegram `callback_data` and is limited to 64 UTF-8 bytes. Keep it short and use an upstream-generated task identifier, for example `task123:solution_a`. Do not place large JSON payloads in callback data.

Buttons are rendered at up to two buttons per row.

## Callback handling

V1 uses Telegram long polling, so no public webhook endpoint is required.

When a user clicks an action button, the service:

1. receives the Telegram `callback_query`;
2. immediately calls `answerCallbackQuery` with `Selection received.`;
3. builds a generic callback event;
4. forwards it to `CALLBACK_FORWARD_URL` when configured;
5. otherwise logs the event and finishes.

The acknowledgement only confirms that this service received the click. It does not mean that an upstream AI or task runner has completed the selected action.

Example event:

```json
{
  "event": "telegram.action",
  "action": "task123:solution_a",
  "chat_id": 123456789,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

A forwarding failure is logged and does not terminate the Telegram polling loop. V1 intentionally has no durable retry queue.

## AI boundary

AI is not implemented in this repository and this service does not guess an AI-specific request format.

The stable V1 boundary is:

```text
upstream -> POST /api/v1/messages -> Telegram
Telegram action -> callback event -> CALLBACK_FORWARD_URL
```

A future AI service only needs to produce the generic message request and/or accept the generic callback event.

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

## Validation rules

- message `text` is trimmed, required, and limited to 4096 characters;
- URL button requires `url` and forbids `action`;
- action button requires `action` and forbids `url`;
- URL button accepts only `http://` and `https://`;
- action callback data is limited to 64 UTF-8 bytes;
- unknown request/model fields are rejected;
- Telegram messages are sent as plain text; V1 does not force Markdown/HTML parse modes.

## Tests

Unit tests never require a real Telegram account. Telegram and upstream HTTP behavior are mocked/faked.

```bash
poetry run pytest -q
```

Coverage includes model validation, API routes, default and overridden chat IDs, button rendering, callback parsing/acknowledgement, callback forwarding, forwarding failures, long-poll recovery, and FastAPI lifespan startup/shutdown.

### Manual Telegram smoke tests

With a real bot token/chat ID, manually verify:

- Test A: plain text message;
- Test B: URL button opens the target page;
- Test C: action button is received and logged;
- Test D: action callback reaches a local mock HTTP receiver configured by `CALLBACK_FORWARD_URL`.

Do not place real secrets in test fixtures, `.env.example`, commits, issues, or logs.

## Relationship to the original Riko Telegram code

The implementation retains the proven integration concepts from `riko-bot`: environment-based token/chat configuration, proxy-aware `python-telegram-bot`, HTTP-triggered message sending, error logging, and 503 behavior for Telegram delivery failure.

It deliberately does not carry over `PackageReportData`, `PackageReportService`, package/version enrichment, Manifest/PR status fields, scheduler/database behavior, or old package-report formatting. The V1 public contract is generic text plus optional buttons.
