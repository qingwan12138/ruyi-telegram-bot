# AI Decision Callback Feedback Design

> Historical completed design: this document records the earlier single-
> consumer callback stage. The current generic multi-workflow architecture is
> defined in `2026-09-16-human-interaction-routing-design.md`; AI is a
> horizontal workflow capability, not a fixed upstream or central router.

## Scope

This change improves the user feedback for generic AI decision callbacks without adding AI inference or AI-specific APIs to this repository.

The Telegram service remains responsible only for:

- sending a question and action buttons supplied by an upstream service;
- acknowledging a user's button click immediately;
- forwarding the generic callback event to `CALLBACK_FORWARD_URL`;
- accepting a later message from the upstream service through the existing `POST /api/v1/messages` endpoint.

The upstream service remains responsible for interpreting actions, storing task context, executing decisions, ensuring business-level idempotency, and reporting progress or results.

## Architecture

The interaction has two asynchronous feedback stages:

```text
AI / upstream creates decision options
  -> POST /api/v1/messages
  -> Telegram displays action buttons
  -> user selects an option
  -> Telegram immediately displays "Selection received."
  -> generic CallbackEvent is posted to CALLBACK_FORWARD_URL
  -> AI / upstream restores the task context and processes the selection
  -> AI / upstream calls POST /api/v1/messages
  -> Telegram displays the processing result
```

The immediate callback acknowledgement means only that this service received the click. It does not mean that the upstream service accepted, started, or completed the selected action.

## Public Contracts

No new route or AI-specific request model is introduced.

An upstream service sends decision options with the existing message contract:

```json
{
  "text": "A dependency conflict was detected. Choose a solution.",
  "buttons": [
    {
      "type": "action",
      "text": "Use solution A",
      "action": "task123:choose_a"
    },
    {
      "type": "action",
      "text": "Use solution B",
      "action": "task123:choose_b"
    }
  ]
}
```

Action values remain opaque to this service. A short convention such as `<task-id>:<verb>` is recommended, but the service does not parse or validate business verbs beyond the existing Telegram callback-data limit.

The existing callback event remains unchanged:

```json
{
  "event": "telegram.action",
  "action": "task123:choose_a",
  "chat_id": 123456789,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

After processing the action, the upstream service sends its result through the existing endpoint, using the callback event's `chat_id`:

```json
{
  "chat_id": 123456789,
  "text": "Solution A completed successfully."
}
```

## Callback Acknowledgement

`TelegramClient.answer_callback_query` will accept an optional acknowledgement text and pass it to Telegram.

`CallbackService` will acknowledge each callback with the fixed text:

```text
Selection received.
```

The acknowledgement is deliberately generic. The service will not inspect the original keyboard to recover the selected button label, expose the opaque action value, modify the original message, or remove its buttons.

The fixed message is not configurable in this change. Adding configuration or localization without a demonstrated requirement would add unnecessary surface area.

## Error Handling and Delivery Semantics

Callback acknowledgement is attempted before callback validation and forwarding so the Telegram client stops showing the loading state promptly.

- If acknowledgement fails, the failure is logged without secret-bearing exception text and forwarding continues.
- If a callback has no action or accessible message, it is acknowledged and then ignored.
- If forwarding returns a non-success status, the status code is logged and the polling loop continues.
- If forwarding encounters a network or unexpected failure, only sanitized error information is logged and the polling loop continues.
- If the upstream service later receives HTTP 503 from `POST /api/v1/messages`, it decides whether and how to retry its result notification.
- Duplicate clicks may produce multiple callback events. The upstream service must enforce business-level idempotency using the task state and/or `callback_query_id`.

V1 retains its existing best-effort forwarding behavior. This change does not add persistence, a retry queue, a database, or a message broker.

## Testing

Automated tests will verify that:

- the Telegram client passes the fixed acknowledgement text to `answerCallbackQuery`;
- callback acknowledgement still occurs before parsing and forwarding;
- a valid callback produces the existing `CallbackEvent` fields without contract changes;
- acknowledgement failure does not prevent forwarding;
- HTTP and network forwarding failures do not escape the callback handler or terminate polling;
- incomplete callbacks are acknowledged but not forwarded;
- logs do not expose Telegram tokens or secret-bearing callback URLs.

Existing tests must remain in place. Documentation examples will describe the immediate acknowledgement separately from the later AI/upstream result notification.

## Explicit Non-Goals

This change does not add:

- an OpenAI, Claude, or other model client;
- model selection, prompts, or AI credentials;
- AI task storage or conversation state;
- package-report, Manifest, PR, or test-failure business models;
- new `/ai`, `/agent`, or task-execution routes;
- synchronous waiting for AI execution inside the callback request;
- editing messages or disabling buttons after a selection;
- a callback retry queue or durable delivery guarantee.

These boundaries keep `ruyi-telegram-bot` a generic notification and human-action transport that can be used by a future AI service over HTTP/JSON.
