# Help calls and automatic messages

This guide describes v1.2.2. It does not require a particular external service.

## Operator workflow

1. Select stations if helpful, then touch the configured support shortcut.
2. **Call queued** means the terminal saved the request, not that it has reached
   the external service. Continue local reporting; do not tap repeatedly to retry.
3. **Help message delivered to the service** appears only after the service
   accepted the request and the terminal saved that acknowledgement. It does not
   mean a person has read or acknowledged it.

The compact **Delivery** control beside the connection notice shows waiting or
review counts. On the narrowest screens the same control uses a count and short
label. Open it to see the destination, saved message, creation time, attempts and
reason for delay. It does not hide stations or block normal reporting.

Automatic lifecycle notifications use the same durable delivery worker. Messages
do not create a response record just because somebody calls for help. New manual
calls use the current connection and shortcut destination; existing incident
updates retain their original connection and equipment routing.

New reports in standalone mode do not enqueue external writes. Its support shortcuts
show **Standalone** and cannot claim that an external call was queued. Switch to
connected reporting in Settings when messages should be sent through a connector.
Previously saved external updates remain preserved and can still finish delivery;
changing reporting mode is not a way to discard that queue.

## If a message does not appear

- **Waiting:** check connectivity, the configured request budget and remote quota.
  Directory lookups consume requests too. The queue retries temporary failures
  without blocking the screen and survives restart.
- **Review required:** read the explanation. Check the destination's membership,
  spelling, permissions and connector mappings. The API account must be allowed
  to post to that exact destination, not merely list it.
- **Uncertain acceptance:** check the external chat before retrying. A timeout
  can occur after the service has accepted a message. The app deliberately holds
  such non-idempotent writes to avoid creating duplicates.
- **Expired help:** the request is too old to send automatically. Use the site's
  escalation process or make a new call for current conditions.

After correcting configuration, **Review / retry** requires the administrator
password. A reviewed message retry refreshes completed recipient-directory
snapshots while retaining unfinished pagination. Unexpired held help requests can
be retried; expired requests cannot.

**Dismiss notice** is available only for held chat messages. Verify the external
chat first, then authorize dismissal. The message leaves the queue without being
sent or marked delivered. The audit log retains its content, destination,
identifier, attempts, last error and authorizing administrator, subject to the
normal storage-retention policy. Dismissal is not available for queued/sending
messages, incident creation, comments, record status, crew or equipment updates.
There is deliberately no unsafe “clear everything” button.

## Configure recipients and connector responses

Set the three manual shortcuts in **Settings → Connection**. Their labels,
destinations and visibility are separate from automatic lifecycle chat routes.
Use `conversation:Maintenance support` to explicitly address a group or
`user:Responder name` for a person. An unqualified name remains valid when it is
unique across the enabled directories. A group/person collision never silently
chooses a recipient. Explicit routes also avoid querying an irrelevant directory.

The connector needs the relevant list operation, message operation and canonical
workflow mappings. Check the mapped directory collection, identifier, display
name and message-content fields. Follow the external service's actual documented
success codes. If it returns an unlisted successful status (for example, HTTP 202
when only 201 is configured), FloorTerminal holds the message for review rather
than repeating a possibly accepted write. Correct the operation's `success_codes`
only after verifying the service contract and the original message.

Never mark a write retry-safe merely to suppress a warning. Declare remote
idempotency only when the service really enforces it. See the
[connector contract](connector.md) and [offline-delivery safeguards](offline-delivery.md).
