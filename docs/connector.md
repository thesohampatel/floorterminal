# External connector contract v1

Application version numbers do not change this file's schema number. Existing
compatible schema-1 connectors are preserved during USB upgrades; do not replace
them with a new release's example. See [update compatibility and preservation](update-data-compatibility.md).

The application contains no built-in service integration, service catalog, or provider-specific implementation. One or more validated, data-only connector files beside the executable define external HTTPS connections. The runtime never imports connector code and never evaluates scripts.

Contract v1 is designed for different external API families without forcing them into one URL or payload shape. It supports conventional REST resources, RPC envelopes, OSLC-style object structures, and OData-style collections. Compatibility still depends on the deployed service exposing the operations required for each enabled capability.

## Canonical response record

In 1.2.0, optional `workflow.group_targets` maps local group IDs to
external asset/location IDs. Optional structured creation fields describe group
impact without changing the Connector v1 version. Read the [group mapping rules](station-groups.md#connector-mapping)
before enabling asset status for independent cells. No mapping means no group
asset-status call, not an implicit whole-line asset change.

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

For a workflow-by-workflow setup checklist, wire examples and acceptance criteria,
read [Connector commissioning](connector-commissioning.md). The additions described
there require **1.2.0 or later**. Use these
extensions only with a compatible application; the contract remains schema v1.

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

Only HTTPS is accepted. The base URL must be literal, without credential substitution.
Resolved operation paths cannot change the base host. When `allowed_hosts` is
nonempty, the base host must appear in it. Fragments, dot-segment paths and control
characters are rejected. Redirects are never followed.

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

Success codes must be in the HTTP 2xx range. A record-creation response must contain
the mapped, usable record ID; an asynchronous job acknowledgement is not a completed
creation. Authentication query fields cannot be overwritten by caller parameters.
JSON responses reject duplicate keys, non-finite numbers and excessive nesting.

`body_schema` is a deliberately small validation subset, not a full JSON Schema
engine. Supported rules are `type` (object/array/string/integer/number/boolean),
`enum`, `required`, `properties`, Boolean `additionalProperties`, `items`,
`minimum`, `maximum`, `minLength` and `maxLength`. Unsupported rules are rejected
at load time. Validation occurs after workflow-field expansion and idempotency
injection but before the operation's outer body envelope is applied.

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

In v1.2.0, the durable worker makes one attempt per scheduled job;
it does not sleep through these inline retries. HTTP 429 or Retry-After produces
a shared cooldown even on a connector with a retry declaration. Non-idempotent
comments/messages with an ambiguous outcome are held for administrator review,
not blindly replayed. To permit safe unattended retries, declare the operation's
real remote idempotency mapping or proven safe retry semantics. The worker supplies
the stable journal UUID to optional idempotency mappings too. This is not a
universal exactly-once guarantee: commissioning must verify remote key retention
and behavior after lost responses. See [offline delivery](offline-delivery.md).

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
| `response_records` | `create_response_record` | Local reporting remains available; queued external creation waits for a capable connector |
| `response_record_status` | `update_response_record_status` | Local lifecycle continues; external status skipped |
| `response_record_comments` | `create_response_record_comment` | Local detail remains; external comments skipped |
| `response_record_assignments` | `update_response_record` | Participation remains local; external assignment skipped |
| `asset_status` | `create_asset_status` | External machine state synchronization skipped |
| `team_directory` | `list_users`, `list_teams`, `list_team_members` | Crew picker and team lookup unavailable |
| `messaging` | At least one send route and its directory: `send_conversation_message` + `list_conversations`, and/or `send_user_message` + `list_users` | External support and lifecycle messages unavailable |

An enabled capability must map all required semantic operations. Disabled capabilities do not require unused endpoints. Thus a system without conversations can still provide response records and asset status, and a system without an asset-state endpoint can still provide response-record tracking.

Group-only and person-only messaging are supported independently. Use a plain
unique display name, or explicitly qualify a destination as `conversation:Name`
or `user:Name`. If both directories contain the same name, an unqualified send is
blocked before any write. Settings suggestions qualify those collisions. Duplicate
names within one directory still require a unique external name. Filters such as
named-groups-only belong in that operation's `static_query`, never application code.

## Create-operation idempotency

For automatic replay after uncertain delivery, each mapped create operation must
declare a deduplication mechanism that the remote service or gateway genuinely enforces:

```json
"idempotency": {
  "location": "header",
  "name": "Idempotency-Key",
  "remote_guarantee": true
}
```

`location` may be `header`, `query`, `body`, or `path`. For `query`, `name` must also
appear in `query_parameters` and cannot conflict with aliases, static or authentication
parameters. For `body`, a dotted path such as `metadata.eventKey` is supported.
For `path`, `name` must identify a placeholder in the operation path; this supports
services with atomically unique external-reference upserts. The same UUID is persisted
before dispatch and reused after restart. Every optional idempotency declaration,
including those for messages or comments, is validated too.

`remote_guarantee: true` is a deployment assertion, not client-side emulation.
Configure it only if the service or gateway atomically associates the key with the
created record and returns the same successful record for repeated keys. Merely
accepting a header, storing an ID in description text, or returning a duplicate-key
409 is not enough. Upsert retries must also avoid duplicate secondary effects.

If the endpoint cannot guarantee this, **do not invent an idempotency header**.
Instead, explicitly configure:

```json
"delivery": {"ambiguous_result": "hold"}
```

This is mutually exclusive with `idempotency` and `retry.safe: true`. It permits a
native create operation without claiming deduplication. The durable worker sends
once; a timeout, interrupted send or uncertain response is held for administrator
review. Definite quota rejection and proven no-request-sent failures can be retried.
Record and asset creation require either valid idempotency or this explicit hold
policy; omission is still rejected. Use a reviewed deduplicating gateway if the
site requires unattended recovery from every ambiguous write.

In **Saved updates**, a held creation can be linked to its verified existing record.
A held asset event can be reconciled using **Verify existing event**, an external
event ID/audit reference and administrator authentication. Verify the exact asset,
state and event time, not just its current Online/Offline value. This records human
verification; it is not an automatic remote read or permission to discard work.
See [delivery recovery](offline-delivery.md).

## Mapping different data models

`workflow.fields` translates canonical names such as title, description, priority,
type, assignees, identifiers, status, asset, location, names, cursor, and message
content. Dotted field paths build nested request objects and read nested response
leaves, including group/station metadata. Array indexes and executable expressions
are not supported. `status_description` names the free-text note of an asset status change;
the terminal fills it with the affected stations, reported failure types, operator
note, and response-record reference, without wall-clock timestamps. `workflow.values` translates canonical lifecycle values into strings or
numeric codes expected externally. `workflow.collections` locates arrays such as
`items`, `data.records`, or `value`. `workflow.objects` locates nested created and
identity objects.

Optional `workflow.objects.created_asset_status` and
`workflow.fields.asset_status_id` normalize a returned asset-event ID. Without an
explicit asset-event object mapping, only success/failure is used; the application
does not guess an external response envelope. Missing configured creation objects,
missing record IDs and invalid directory arrays are errors, not successful empty data.

Identifiers remain opaque by default. If an external request schema requires a
particular JSON scalar type, `workflow.field_types` can declare `string`, `integer`,
`number`, or `boolean` for canonical fields such as `asset_id`, `location_id`, and
`assignee_id`. Invalid conversion fails before transport rather than sending a
mis-typed request. Fractional identifiers, Boolean numeric IDs and non-finite
numbers are rejected rather than truncated. Example:

```json
"field_types": {
  "asset_id": "integer",
  "location_id": "integer",
  "assignee_id": "integer"
}
```

### Assignment object formats

By default, an assignee is a typed object with separate discriminator and ID
fields, such as `{"type": "TEAM", "id": "team-7"}`. Map `assignee_type`,
`assignee_id` and `workflow.values.assignee_type` to the actual schema.

Some APIs instead distinguish the object by its ID key. For those, declare **both**
`workflow.fields.team_assignee_id` and `workflow.fields.user_assignee_id`:

```json
"fields": {
  "assignees": "assigned_to",
  "team_assignee_id": "team_id",
  "user_assignee_id": "person_id"
},
"field_types": {
  "assignee_id": "integer"
}
```

This produces `"assigned_to": [{"team_id": 7}, {"person_id": 12}]`, not a
discriminator/ID object. Keys are illustrative and must match the external schema.
The two mappings must be nonempty and distinct; partial configuration is rejected.
Optional per-kind `field_types.team_assignee_id` / `user_assignee_id` overrides
take precedence over `assignee_id`. Creation and later crew replacements use the
same mapping. Removing everyone sends an empty list unless the intended team is
retained. Check that the assignment endpoint replaces the list, rather than only
appending participants; a connector cannot invent removal semantics.

### Per-station and group metadata

Explicit creation mappings may include `group_ids`, `group_names`,
`reported_stations`, `affected_stations`, `asset_ids`, `location_ids`,
`impact_scope`, `incident_id` and `failure_details`. The last is an array of objects
with `station` (literal name), `reasons` (selected strings), and `note` (text).
It records only reported stations, not a fabricated fault on every linked station.
No scalar `field_types.failure_details` conversion is allowed. Full values are
saved with the incident and queued intent; catalogue edits cannot retarget or
rewrite those saved deliveries.

These are optional remote fields, not an assumption that every API accepts them.
Existing unmapped connectors continue using descriptive reporting. Multiple local
groups do not imply that an API supports multiple native asset relations; see
[group mapping](station-groups.md#connector-mapping) for scalar and array behavior.

### Identity and directory reads

To show the authenticated account name in the header, set
`identity.authenticated_subject_id`, map `workflow.operations.load_user`, and set
`workflow.objects.loaded_identity` to the response object path (empty means the
response root). Leave the subject ID empty when the API has no safe self/user
lookup; the UI then shows the connector as connected without inventing an identity.

Cursor and OData token pagination can be represented using query aliases plus the
mapped `next_cursor` field. Directory, conversation, user, team, and team-member
lookups follow pages up to `directory_max_pages` (default 3). An empty cursor ends
the directory. A repeated cursor or a nonempty cursor at the page cap is an error,
never a supposedly complete directory from which to choose a recipient. A quota
pause retains partial progress so the next attempt resumes at its saved cursor.
Optional operation `directory: {"page_size": 50}` controls page size (1–2000,
default 200; use the service's documented maximum). `limit` is sent only when
declared, including through a query alias. Empty collection paths support APIs
returning a bare array; such responses must actually be unpaginated. The lookups
remain subject to the configurable application-wide rolling
request budget. `connection.requests_per_minute` accepts any positive integer
(the example starts at 10). In 1.2.0, the administrator can override
it using `api_requests_per_minute` in Settings/config; blank/null inherits the
connector value. Provider quota and backoff rules still apply, including
case-insensitive quota headers and HTTP `Retry-After`. A lookup may span several
request windows. Offset/page-number APIs that cannot expose their next token
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

Production acceptance testing must separately prove any declared idempotency with
commit-then-response-loss tests, or verify held-write recovery for endpoints without
that guarantee. It must also cover permissions, response fields, pagination,
assignment replacement, lifecycle values, asset-state meanings, original event
timestamps, quotas and partial failures. Do not claim `remote_guarantee` merely
because a key is accepted syntactically or appears in descriptive documentation.

Each durable delivery records its attempt count before dispatch. `delivery_confirmed`
and `delivery_deferred` events identify the journal operation; protected retry,
existing-record linking and expired-help acknowledgement have separate audit
events. Legacy queue-conversion events remain distinguishable from actual external
acceptance. This preserves evidence if a service violates its declared guarantee.
