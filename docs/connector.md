# External connector contract v1

The application contains no built-in service integration, service catalog, or provider-specific implementation. One or more validated, data-only connector files beside the executable define external HTTPS connections. The runtime never imports connector code and never evaluates scripts.

Contract v1 is designed for different external API families without forcing them into one URL or payload shape. It supports conventional REST resources, RPC envelopes, OSLC-style object structures, and OData-style collections. Compatibility still depends on the deployed service exposing the operations required for each enabled capability.

## Canonical response record

A **response record** is the console's provider-neutral lifecycle object for one
reported interruption or planned line intervention. It is not the name of an
external vendor resource. A deployment connector translates it to whichever
ticket, task, case, job, request, or other record model the selected operations
system exposes. Application code uses only the canonical response-record actions
and fields; external paths, payload keys, status values, and response extraction
remain data-driven connector mappings.

The canonical create result contains an opaque `id` and may contain a human-facing
`reference`. If an external API uses a differently named identifier or sequence
field, map it with `workflow.fields.response_record_id` and
`workflow.fields.response_record_reference`. Never encode a vendor field name in
application code.

## Safe deployment model

The distributed connector is disabled, has no base URL, and contains empty credentials. Local station selection, failure capture, timers, state persistence, logs, Settings, and the touchscreen interface remain available. Network actions clearly show as unavailable until their own capabilities are configured.

1. Build or obtain the neutral release.
2. Create a deployment-specific `connector.json` from the neutral template.
3. Configure the protocol, HTTPS base URL, credentials, authentication templates, operations, mappings, and accurate capabilities.
4. Keep unsupported capability flags `false`; never create dummy endpoints.
5. Place the file beside the executable and restrict it to the application account (`chmod 600 connector.json` on Linux).
6. Open protected Settings to see every detected file, local validation errors, readiness, protocol, and enabled features. Connector technical fields are intentionally read-only in the GUI.
7. Validate each enabled action against an authorized non-production environment before line-side deployment.

Never place credentials, private URLs, personal data, or third-party proprietary documentation in source control, build history, logs, screenshots, or issue reports. Release builds reject enabled connectors and nonempty credentials.

## Automatic discovery and multiple files

At startup and when Settings is opened, the application scans only its deployment directory, never subdirectories, for `connector.json`, `*.connector.json`, `*_connector.json`, `*-connector.json`, `connector-*.json`, and `connector_*.json`. Symlink targets outside that directory are ignored and at most 32 files are considered.

Each file is parsed and validated offline without making an external request. Invalid files appear with their exact safe validation error and do not prevent valid files from operating. If exactly one connector is ready, it is selected automatically. With multiple files, `connector.json` is preferred initially; a user can select another valid file in protected Settings. The selected filename is stored in owner-only `.active_connector`. Only one connector drives a terminal at a time.

Protected Settings includes a create-new-only wizard for a simple REST starting point. It accepts an HTTPS base URL, bearer token or `X-API-Key`, and a safe GET diagnostic path; writes a new owner-only connector atomically; selects it; and immediately runs the existing explicit diagnostic. The generated file is intentionally diagnostic-only with every workflow capability disabled. Existing connector files are never modified, and response-record, directory, messaging, asset, response mapping, and idempotency semantics must still be added and acceptance-tested by an integration engineer.

## Contract sections

- `schema_version`: must be `1`.
- `contract`: fixed contract name and version `1.0`.
- `identity`: deployment-facing connector name/description and an optional
  `authenticated_subject_id` used only when the external API exposes a direct
  user/account lookup.
- `connection`: protocol family, HTTPS base URL, timeout, request budget, and host allow-list.
- `credentials`: arbitrary deployment-owned secret and tenant fields. They are loaded from the file but never displayed or edited by Settings.
- `authentication`: required credentials, derived credentials, and header/query/body templates.
- `capabilities`: independent feature switches.
- `workflow.operations`: maps canonical application actions to declared operations.
- `workflow.collections`, `objects`, `fields`, `field_types`, and `values`:
  response, payload, wire-type, and state translation.
- `operations`: HTTP method, path, queries, headers, body encoding/envelope, response root, success codes, and retry declaration.
- `response`: rate-limit header and error-status normalization.
- optional `diagnostics`: one explicitly safe GET operation and its allow-listed query values.

## Connector test in Settings

The **Test Selected Connector** action first repeats complete local schema, credential-presence, HTTPS, host, operation, mapping, and capability validation. When the connector declares `diagnostics.test_operation`, the operation must exist and use `GET`; its optional query keys must be allowed by that operation. A typical definition is:

```json
"diagnostics": {
  "test_operation": "user.list",
  "query": {"limit": 1}
}
```

Only an authenticated user action starts the test. It sends at most one request, never follows redirects, never sends a request body, and never invokes creation, update, messaging, assignment, status, or deletion operations. Success confirms request construction, TLS/host policy, authentication acceptance, permission for the selected read operation, an accepted HTTP status, and valid JSON/response-root handling. It does not certify every capability or endpoint. Failure is shown without exposing credentials or response bodies. If no explicit diagnostic exists, the application may use the first mapped safe directory GET; if none exists, it reports local validation only and performs no network request.

## Protocol families

`connection.protocol` accepts `rest`, `rpc`, `oslc`, or `odata`. This value documents and validates the intended integration style; behavior remains fully controlled by the operation definitions.

- `rest`: resource-oriented paths and JSON bodies.
- `rpc`: commonly one POST endpoint with an action/service envelope around the canonical payload.
- `oslc`: installation-defined object structures, static query flags, API-key headers, and method-override headers.
- `odata`: `$top`, `$skiptoken`, and `value` response collections through query aliases and collection mappings.

Only HTTPS is accepted. Resolved operation paths cannot change the base host. When `allowed_hosts` is nonempty, the base host must appear in it. Redirects are not followed to construct requests.

## Authentication

Authentication type may be `headers`, `api_key`, `basic`, `bearer`, or `custom`. The type is descriptive; templates define the actual wire representation.

Header example:

```json
{
  "credentials": {"access_token": "", "tenant_id": ""},
  "authentication": {
    "type": "bearer",
    "required_credentials": ["access_token"],
    "headers": {
      "Authorization": "Bearer ${access_token}",
      "X-Tenant-Id": "${tenant_id}"
    },
    "query": {},
    "body": {},
    "derived_credentials": {}
  }
}
```

A header whose only referenced optional credential is empty is omitted. Required credentials must be present before the connector reports Ready. Header values reject line breaks.

Derived credentials support `none`, `base64`, and `urlencode` transforms. This permits Basic-style authentication without storing an encoded duplicate:

```json
"derived_credentials": {
  "basic_token": {
    "template": "${username}:${password}",
    "transform": "base64"
  }
}
```

`authentication.query` adds credential templates as query parameters. `authentication.body` inserts credentials into JSON or form bodies; dotted names create nested objects. Authentication values, bodies, and complete URLs are excluded from structured logs.

## Operations and request transformation

Each operation declares:

- `method`: `GET`, `POST`, `PUT`, `PATCH`, or `DELETE`;
- `path`: relative path beginning with `/`, with URL-encoded placeholders such as `{id}`;
- `query_parameters`: complete allow-list for the operation;
- optional `query_aliases`, such as `limit` to `$top`;
- optional `static_query` and credential-safe `headers`;
- optional `body` definition;
- optional `body_schema` for strict canonical-payload validation;
- optional `response_body_path` for nested response roots;
- `success_codes` and an optional, explicitly safe retry declaration.

A retry declaration is bounded to three total attempts and five seconds of fixed
backoff. Every attempt consumes the terminal's rolling request budget. Retries are
off unless `safe` is literally `true`; `retry_on` lists HTTP error statuses and
`network_errors` controls transport-failure retry:

```json
"retry": {
  "safe": true,
  "retry_on": [429, 502, 503, 504],
  "network_errors": true,
  "max_attempts": 2,
  "backoff_seconds": 1
}
```

Declare this only when repeating the exact operation cannot create another event
or apply a second side effect. Create operations additionally require the remote
idempotency guarantee below. Application-level delayed synchronization persists
the same logical intent across restarts; transport retry is only a short,
connector-declared optimization.

The body definition supports `json`, `form`, or `none`, a static envelope, and a dotted `payload_path`:

```json
"body": {
  "encoding": "json",
  "static": {"service": "work", "action": "create"},
  "payload_path": "parameters.record"
}
```

A canonical `{ "title": "Stopped" }` payload becomes:

```json
{
  "service": "work",
  "action": "create",
  "parameters": {"record": {"title": "Stopped"}}
}
```

## Canonical capabilities

Capabilities are Boolean and isolated:

| Capability | Required semantic operation(s) | Behavior when false |
|---|---|---|
| `response_records` | `create_response_record` | Problem and planned-work creation disabled |
| `response_record_status` | `update_response_record_status` | Local lifecycle continues; external status skipped |
| `response_record_comments` | `create_response_record_comment` | Local detail remains; external comments skipped |
| `response_record_assignments` | `update_response_record` | Participation remains local; external assignment skipped |
| `asset_status` | `create_asset_status` | External machine state synchronization skipped |
| `team_directory` | `list_users`, `list_teams`, `list_team_members` | Crew picker and team lookup unavailable |
| `messaging` | `list_users`, `list_conversations`, two send operations | Support and lifecycle messages unavailable |

An enabled capability must map all required semantic operations. Disabled capabilities do not require unused endpoints. Thus a system without conversations can still provide response records and asset status, and a system without an asset-state endpoint can still provide response-record tracking.

## Create-operation idempotency

`response_records: true` and `asset_status: true` are accepted only when each mapped create operation declares a deduplication mechanism that the remote service or gateway genuinely enforces:

```json
"idempotency": {
  "location": "header",
  "name": "Idempotency-Key",
  "remote_guarantee": true
}
```

`location` may be `header`, `query`, or `body`. For `query`, `name` must also appear in the operation's `query_parameters`; for `body`, a dotted path such as `metadata.eventKey` is supported. The terminal generates one UUID before each logical create event, persists it before the network attempt, and supplies that exact value on every retry. This covers unplanned response records, planned response records, and asset OFFLINE/ONLINE status creation.

`remote_guarantee: true` is a deployment assertion about external behavior, not client-side emulation. Configure it only if the service or a controlled gateway atomically associates the key with the created record and returns the same successful record for repeated keys after an ambiguous timeout. A system without that guarantee must use an idempotent gateway or disable the affected capability. Merely storing the key as descriptive text is insufficient.

## Mapping different data models

`workflow.fields` translates canonical names such as title, description, priority,
type, assignees, identifiers, status, asset, location, names, cursor, and message
content. `workflow.values` translates canonical lifecycle values into strings or
numeric codes expected externally. `workflow.collections` locates arrays such as
`items`, `data.records`, or `value`. `workflow.objects` locates nested created and
identity objects.

Identifiers remain opaque by default. If an external request schema requires a
particular JSON scalar type, `workflow.field_types` can declare `string`, `integer`,
`number`, or `boolean` for canonical fields such as `asset_id`, `location_id`, and
`assignee_id`. Invalid conversion fails before transport rather than sending a
mis-typed request. Example:

```json
"field_types": {
  "asset_id": "integer",
  "location_id": "integer",
  "assignee_id": "integer"
}
```

To show the authenticated account name in the header, set
`identity.authenticated_subject_id`, map `workflow.operations.load_user`, and set
`workflow.objects.loaded_identity` to the response object path (empty means the
response root). Leave the subject ID empty when the API has no safe self/user
lookup; the UI then shows the connector as connected without inventing an identity.

Cursor and OData token pagination can be represented using query aliases plus the
mapped `next_cursor` field. Directory, conversation, user, team, and team-member
lookups follow pages up to `directory_max_pages` (default 3), stop on an empty or
repeated cursor, and remain subject to the application-wide rolling limit of at
most 10 requests per minute. Choose a page limit that keeps a worst-case lookup
within that budget. Offset/page-number APIs that cannot expose their next token
through this mapping need a reviewed gateway.

## Limits of a data-only connector

A connector can represent HTTP operations, authentication templates, envelopes, mappings, and independent capabilities. It intentionally cannot run arbitrary code. A remote system requiring proprietary SDK execution, interactive browser login, cryptographic signing not supported by templates, or complex conditional orchestration needs a separately reviewed gateway that exposes this canonical HTTPS contract. This security boundary prevents a deployment file from becoming executable code.

## Offline verification

The automated suite injects an in-memory transport and never contacts an external
host. It verifies REST requests, RPC envelopes, form bodies, derived Basic
credentials, API-key/query authentication, OSLC-style headers, OData
aliases/collections, bounded pagination, optional identity loading, HTTPS and
allow-list enforcement, response extraction, field/value/type mapping, opaque and
numeric identifiers, rolling request budgets, declared safe retry, capability
isolation, idempotency injection and stable-key delayed retry, and release
credential exclusion. A full application-boundary test also enables the
distributed Connector v1 contract, reports downtime through `FloorTerminalApp`,
verifies the prepared POST/idempotency header, accepts the simulated remote
response-record response, and confirms that local queued/UI state is cleared
correctly.

Production acceptance testing must separately prove response-record and asset-status idempotency with commit-then-response-loss tests, as well as permissions, response fields, pagination, assignment replacement semantics, lifecycle values, asset-state meanings, timestamps, rate-limit headers, timeout recovery, and partial-failure handling. The connector must not claim `remote_guarantee` based only on documentation or because the key is accepted syntactically.

Every synchronization attempt is counted in durable state. Attempt two and later emit `downtime_sync_retry_after_previous_attempt` with the stable report ID and attempt number, even though enabled response-record connectors are required to provide remote idempotency. This preserves forensic visibility if an external system violates its declared guarantee.
