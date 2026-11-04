# Connecting an operations system

This guide is for integration engineers configuring **FloorTerminal 1.2.0**.
No provider account, endpoint or secret ships with the application.
The connector is data, not executable adapter code. Keep your completed file
private beside the executable; never commit it or attach it to an issue.

Read the [contract reference](connector.md) for exact field names and
[offline recovery](offline-delivery.md) before enabling writes.

## 1. Establish what the remote system actually supports

Use the service's official documentation and your organization's permissions.
Do not infer an endpoint from the label shown in its website. Plan availability,
organization scope, user permissions and API behavior can differ.

| Terminal action | Remote contract to verify | Local behavior that must remain intact |
|---|---|---|
| Report a problem | Create record; title, description, priority, type; accepted status and returned ID | Selected stations, failure reasons, notes and original start time are saved before sending |
| Operator self-fix | Same create operation, with self-fix context in descriptive reporting | One incident; Engineering may join later without resetting elapsed downtime |
| Planned work | Same create operation with the configured planned/preventive value | Separate planned category and normal release confirmation |
| Engineer arrives | Read/cache complete team members; replace assignments; set progress status; optionally add comment/message | Cached names and participation remain usable offline; routine opening does not refetch the roster |
| Update crew | Replacement versus additive assignment semantics, team/user discriminator and ID types | Joined/left participation remains in local history and descriptive reporting |
| Release production | Completion comment/status; asset Online event; optional notifications | First confirmed release time is authoritative, even if saving/delivery must retry |
| Call support | Group and/or person message endpoint; unique recipient resolution | Does not create another response record; unavailable routes do not disable local reporting |
| Independent groups | Exact group-to-asset/location mapping | Unaffected groups keep running; shared assets return Online only after their last affected group releases |

**A progress status is not a remote labor timer.** FloorTerminal measures incident
and response durations locally and reports them through configured descriptive
fields/comments. It does not imply that changing status starts another system's
stopwatch, timesheet, billing timer, machine controller or safety interlock. Native
time-entry APIs need a separately reviewed extension/gateway; do not relabel a
status endpoint as a timer endpoint.

Asset availability is a separate capability, not a consequence of a record comment.
Map its actual state-change endpoint. Original stop/release timestamps are sent
when `started_at` is supported; the remote system must accept retrospective events
if historical downtime is to remain accurate after an outage.

## 2. Map authentication and scope

Set a literal HTTPS `connection.base_url`, explicit host allow-list, timeout and
request budget. Authentication can use header, query or body templates, including
derived Basic credentials. Prefer headers where supported; URLs containing query
credentials may be logged by infrastructure outside FloorTerminal's control.

Keep tenant/organization scope consistent across the connector identity, credentials
and all operations. The queue binds to the configured base URL and identity, not
to secret token bytes, so routine key rotation does not orphan saved updates.
If changing organizations/accounts behind the same URL, use a distinct connector
identity and verify the destination before resuming. The application cannot infer
the organization represented by an opaque replacement token.

The budget is this installation's request ceiling, not a percentage of someone
else's already-consumed quota. Settings can override the connector's default.
Every lookup, diagnostic and retry uses the same rolling ledger. Remote quota
exhaustion and backoff still take precedence.

## 3. Choose honest delivery guarantees

An operation that creates an append-only history row is not automatically safe
just because the payload describes the same state.

### Documented external-reference upsert

For a service with an atomically unique external-reference route, a generic
operation can look like this (illustrative paths, not a ready-made connector):

```json
{
  "method": "PATCH",
  "path": "/tickets/by-reference/{event_key}",
  "query_parameters": [],
  "success_codes": [200, 201],
  "idempotency": {
    "location": "path",
    "name": "event_key",
    "remote_guarantee": true
  }
}
```

Map `workflow.objects.created_response_record` to the returned object and
`workflow.fields.response_record_id` to its actual ID. Verify that retries return
that same ID, including after a process restart. Also verify secondary effects:
upserts can update fields, unarchive records or trigger automations. Those effects
must be acceptable for the same immutable queued intent. Never set the guarantee
solely because a unique field exists or a duplicate POST returns 409.

### No remote deduplication

Use `"delivery": {"ambiguous_result": "hold"}` instead of `idempotency`.
This sends the intent without inventing an unsupported header. Uncertain writes
stop for administrator review, not automatic replay. In Saved updates:

- Check whether the exact record exists; link its ID if it does.
- For an asset-history event, verify its asset, state and original event time, then
  use **Verify existing event** and provide the external event/audit reference.
- If definitely absent, authorize a reviewed retry.
- If presence cannot be established, leave it held and escalate to the service
  administrator. Do not guess or delete local state to clear the warning.

These are attributed human decisions protected by the Settings password. The
application does not certify the evidence automatically. For fully unattended
ambiguity recovery, use a reviewed gateway that really implements deduplication.

## 4. Match payload and response shapes

IDs may be numeric even when entered as text. Set `workflow.field_types` for
`asset_id`, `location_id` and `assignee_id` as required by the request schema.
Map team/user discriminator values separately from their IDs. Ensure assignment
updates mean the complete current crew plus the intended team, not append-only
membership. Removing a participant locally must produce the intended remote state.
For keyed-ID assignment objects, configure both `team_assignee_id` and
`user_assignee_id` instead of the discriminator/ID pair; see the
[assignment formats](connector.md#assignment-object-formats). Test initial team
assignment, arrival, joining/leaving and removal of the last person.

For structured group metadata, dotted field mappings create nested objects:

```json
"fields": {
  "group_ids": "metadata.groups",
  "affected_stations": "metadata.stations",
  "incident_id": "metadata.event",
  "failure_details": "metadata.failures"
}
```

Only map fields supported by the remote schema. Human-readable descriptions and
comments retain context even without custom structured fields. One record does
not imply support for multiple native asset relations: use the documented group
mapping in [Station groups](station-groups.md#connector-mapping).
Include Others-only, several reasons at one station, and different reasons across
multiple reported stations. Indirectly stopped stations must not acquire invented
diagnoses. Check group-only and whole-line scope, shared-asset last release and
missing mappings. Parent/child asset status cascades are never assumed.

Nested collection/object roots and dotted scalar leaves are supported. An empty
collection path means a bare array, not an instruction to ignore pagination.
Unconfigured asset-event response envelopes are not guessed. Optional
`objects.created_asset_status` and `fields.asset_status_id` normalize an event ID.

## 5. Verify directories and recipients

Declare only real query parameters. Put service-specific filters in `static_query`.
Use `query_aliases` for canonical `limit`/`cursor`, and an operation-level
`directory.page_size` no greater than the remote maximum. Map `next_cursor` to its
response field. Never use a returned next-page URL as an unrestricted request URL.

Page caps, repeated cursors and malformed collections fail visibly rather than
silently selecting from an incomplete directory. Narrow the scope or raise the
configured page count within its bounded limits. Completed snapshots expire;
partial lookups resume after quota pauses. A one-request-per-minute budget is
supported but may take several windows to resolve recipients and deliver writes.

For messaging, declare only supported send routes. `conversation:Maintenance`
selects a group; `user:Alex Smith` selects a person. Plain names work when unique
across all supported directories. Same-name group/person collisions require an
explicit prefix; duplicate names within a directory must be made unique there.

## 6. Understand validation evidence

**READY** means the local definition is valid, enabled and has required credentials.
It is not proof of connectivity, entitlement or successful writes. **Test Selected
Connector** performs at most one body-free GET, with no automatic retry. It does
not create, modify or send anything to prove those permissions.

Repository tests use isolated, neutral in-memory transports with real sockets
blocked. They cover request shapes, nested mappings, numeric IDs, upsert keys,
held native writes, restart recovery, original event times, pagination, one-request
budgets, independent message routes and invalid input. Passing these tests does
not certify any remote account or service's production behavior.

Before deployment, an authorized site owner must test an approved non-production
environment: the complete report/respond/release cycle, operator handover, crew
changes, planned work, support-only messaging, independent/shared group assets,
pagination beyond one page, 429/backoff, response loss after a committed write,
power loss, reconnect and administrator reconciliation. Check both local history
and the remote records/events. This repository review does not perform those
external acceptance tests.
