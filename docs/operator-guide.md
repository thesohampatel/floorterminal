# Operator guide

Site safety and escalation procedures always take precedence over this console.

## Screen regions

- **Header:** application/line identity, connector state, time, software update, Information, Settings.
- **Status:** redundant face/glyph, text, description, border, color, and motion.
- **Production map:** stations, conveyor, failure selector, whole-line selection.
- **Guidance:** the next valid action for the current workflow state.
- **Primary actions:** unplanned reporting and planned Engineering work.
- **Support:** message-only Engineering, Quality, and Production requests.
- **Notifications:** transient feedback away from controls plus persistent sync state.

## Report an interruption

1. Make the area safe and follow emergency/isolation procedures first when required.
2. Touch all affected stations or select the whole line.
3. Optionally select failures per station. **Clear** removes failure choices without
   deselecting the station. **Others** accepts appropriate operational context only.
4. Press **Report a problem**, review, and confirm.
5. Verify the status/timer. A queued badge means local capture succeeded but external
   synchronization is incomplete; do not create a second incident to clear it.

## Record response and completion

1. A responder opens the highlighted arrival/start action.
2. Search or select one or more names and confirm.
3. Reopen it later to add a joining responder or remove one who leaves.
4. After approved inspection, guarding, permits, and production release, complete the
   work. Confirm the running state and final duration. Retry queued synchronization
   only through the explicit action/site outage procedure.

Once an external response record exists, a failed status, responder-assignment,
comment, asset, or chat update is queued and shown without blocking the local repair
timer or a safe Production release. Queued updates are kept in the saved state, so
they survive a restart, and are retried in the background at a bounded cadence; a
connector rate limit only delays them. Completion chats state whether the record's
DONE status and the asset's Online state have actually synchronized. Touch the
**Sync pending** chip in the header to retry immediately. A queued external update
is not permission to skip site communication or the authoritative physical release
procedure.

Releasing the line is saved as one step. If it cannot be saved, the terminal keeps
the previous saved state and explains the failure; confirming again later records
the original release time, which the confirmation dialog shows.

## When something fails

A failed action opens a message that names the operation (for example
**Completing repair**), shows the reason, and states the line status that is
actually saved. It stays on screen until **OK, continue** is touched, so it can be
read and reported. The screen always matches the saved state; nothing needs to be
re-entered unless the message says so. If the same failure repeats, note the time
shown and contact the person responsible for the terminal.

The responder list is an operational participation record, not attendance,
timekeeping, payroll, or shift reporting.

## Support and planned work

Support controls send contextual messages and do not create response records. If
the connector's request budget is momentarily exhausted, the request is queued and
retried for up to 15 minutes; delivery is not guaranteed. After that it is
discarded as stale. Use the site's usual escalation route if help has not arrived. Station
selection is optional. Planned Engineering work requires an affected selection and
uses distinct text/status while following the same responder and restoration process.

A completion message reports **DONE** only after successful external acceptance.
If that update is still queued, it says so. If a queued update expired, was rejected,
or was dropped at the queue limit, it says **DONE not confirmed**; check and reconcile
the external record. Local Production release and external synchronization are
separate facts. The release time is captured when **Yes, confirm** is pressed, not
when the confirmation dialog opens.

## Offline and recovery behavior

Reports are stored before synchronization. Retries preserve the event's idempotency
key. If strict state validation presents a recovery screen, follow the documented
recovery procedure—never delete state merely to force a running display.

**Information** documents version, maintainer/contact route, MIT terms, privacy,
security, safety boundaries, and warranty exclusions. **Settings** requires
administrator authorization and controls stations/failures, workflow, messages,
appearance, sounds, storage/logs, and connector selection/testing.

## Software update indicator

The round indicator between the clock and **Information** reports update status:
green when this terminal runs the newest published version, amber when an update
drive is ready or a newer version exists, and red when availability could not be
checked. Nothing about reporting or restoration changes with its colour, and no
version is ever installed without administrator authorization on this screen.

Touch it to see the running version, what that version contains, what a waiting
version changes, and the recorded update history. Follow the
[update guide](update-user-guide.md) to perform an update or a rollback.
