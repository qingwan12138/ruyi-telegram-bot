# Human Interaction Routing Design

## Goal

Incrementally evolve `ruyi-telegram-bot` from one opaque action routed to one
`CALLBACK_FORWARD_URL` into a generic human-interaction transport with logical
target routing and separate received/delivered/failed user feedback.

The service remains limited to notification transport, callback routing, and
delivery status. It does not interpret option semantics, restore workflow
business context, run AI, or add durable storage.

## Architecture and Boundaries

The original Riko responsibilities are split across test, package/PR, and
Telegram services. AI may participate inside any workflow but is not a central
router. A workflow sends a human-interaction request to this service, Telegram
collects the selection, and this service delivers a generic result to the
configured consumer for that interaction.

This change does not add a database, Redis, a message queue, retries, workflow
business logic, a model client, API authentication, or a Telegram free-text
state machine.

## Public Interaction Model

`MessageRequest` gains optional `interaction_id` and `callback_target` fields.
`Button` gains optional `option_id` while retaining optional `action` for
legacy callers. Unknown fields remain forbidden.

Button validation is structural:

- a URL button requires an HTTP(S) `url` and forbids `option_id` and `action`;
- a new action button requires a non-blank `option_id` and forbids `url` and
  `action`;
- a legacy action button requires a non-blank `action`, forbids `url` and
  `option_id`, and must not start with the reserved `h1|` prefix;
- one request cannot mix new and legacy action buttons;
- a request containing new action buttons requires a non-blank
  `interaction_id`;
- interaction fields are not accepted on requests without new action buttons.

Manual review is an ordinary option. Button count remains dynamic from zero to
N, with the existing maximum of two buttons per rendered row.

Whether `callback_target` names a configured target is deliberately not a pure
Pydantic concern. The route/service layer validates it against the runtime
routing registry before Telegram receives a button.

## Callback Data Codec

New interactions use this versioned, stateless encoding:

```text
h1|<target-character-count>|<interaction-character-count>|<target><interaction><option>
```

The two length values are decimal Unicode character counts, matching Python
string slicing after Telegram returns the callback data. The final encoded
callback data is independently limited to 64 UTF-8 bytes. An empty target is
encoded with target length zero and represents use of the legacy/default
`CALLBACK_FORWARD_URL` fallback for a new interaction.

The decoder only treats data starting with `h1|` as the new protocol. It must
return a controlled malformed-data failure for an invalid prefix when invoked
as a new-protocol decoder, non-decimal or missing lengths, negative or
otherwise invalid lengths, slice bounds beyond the payload, trailing layouts
that produce an empty interaction ID or option ID, and payloads exceeding 64
UTF-8 bytes. Malformed callback data must never escape the polling handler or
be reinterpreted as a legacy action.

Legacy actions are sent unchanged as Telegram callback data, except that the
`h1|` prefix is reserved and therefore rejected at request validation time.
No in-memory interaction map is used, so a process restart does not lose the
ability to decode a new callback.

## Routing Registry

`CALLBACK_TARGETS_JSON` contains a JSON object mapping logical target names to
HTTP(S) endpoints. `Settings.load` parses and validates the configuration at
startup. Keys must be non-blank strings, values must be valid `http://` or
`https://` URLs with a host, and malformed JSON or invalid entries fail early.
No endpoint or credential-bearing URL is written to logs.

Routing semantics are:

1. A new callback with a non-empty target resolves only through the registry.
2. An unknown explicit target is an error and never silently falls back.
3. A new callback with an empty encoded target uses `CALLBACK_FORWARD_URL`.
4. A legacy action uses `CALLBACK_FORWARD_URL`.
5. Any action-button request without a resolvable delivery route is rejected
   with HTTP 422 before sending a Telegram message.

The caller cannot submit a callback URL. Adding a target requires only a
configuration change and no callback-routing branch.

## Callback Results and Compatibility

A new selection produces:

```json
{
  "event": "telegram.interaction.selected",
  "interaction_id": "decision-789",
  "option_id": "option-2",
  "chat_id": 123,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

The workflow identified by the routing target restores all business context
from `interaction_id`. The Telegram service stores and transports no package,
test, patch, PR, prompt, reasoning, or option-semantic data.

Legacy callbacks retain `event="telegram.action"` and the original `action`
field and are delivered only to `CALLBACK_FORWARD_URL`. Plain text, URL
buttons, chat ID override, health/version endpoints, proxy behavior, Telegram
503 behavior, lifespan, and polling behavior remain compatible.

The one intentional legacy contract change is that action-button message
requests are rejected when no delivery route exists; the previous log-only
dead-button behavior is removed.

## User Feedback and Failure Handling

Callback handling always attempts the immediate acknowledgement first:

```text
Selection received.
```

Acknowledgement failure is logged safely and does not prevent delivery. After
target resolution and HTTP POST:

- a successful HTTP response triggers a Telegram message containing exactly
  `Selection delivered successfully.`;
- unknown routing, malformed new callback data, timeout, network failure, 4xx,
  or 5xx triggers a Telegram message containing exactly
  `Failed to deliver your selection.`.

Delivery-feedback send failures are logged without secrets and do not escape
the callback handler or stop polling. These messages report transport status
only and never claim that AI, testing, packaging, a PR, or another business
workflow succeeded.

## Configuration and Metadata

`.env.example` and README document `CALLBACK_TARGETS_JSON` and the legacy
fallback meaning of `CALLBACK_FORWARD_URL`. The project name becomes
`ruyi-telegram-bot`, and `pyproject.toml` records the existing Apache-2.0
license using metadata supported by the current Poetry configuration.

## Testing Strategy

Implementation proceeds test-first in incremental phases:

- model tests cover plain text, URL-only requests, one/two/three-or-more new
  options, manual review, blanks, forbidden/mixed fields, unknown fields, and
  the reserved legacy prefix;
- codec tests cover exact 64-byte and over-limit payloads, multibyte UTF-8,
  Unicode character-count lengths, empty fallback target, round trips, and all
  malformed decoder cases;
- configuration and route tests cover multiple registry targets, runtime
  validation, unknown targets, fallback behavior, no-route rejection, and
  arbitrary callback URL rejection;
- callback tests cover ordering, metadata, new and legacy events, success,
  each HTTP failure class, unknown routes, malformed payloads, safe logging,
  feedback-send failures, and poller survival;
- the existing regression suite continues to cover stable transport behavior.

Final verification runs the full pytest suite, Python compileall, configuration
metadata checks, diff validation, and a secret scan. Real Telegram smoke tests
run only when usable credentials are present; otherwise each is reported as
`NOT RUN`.
