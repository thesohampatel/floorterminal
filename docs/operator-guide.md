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

Once an external response record exists, a failed status, responder-assignment, or
asset update is queued and shown without blocking the local repair timer or a safe
Production release. The connector update is retried in the background at a bounded
cadence. A queued external update is not permission to skip site communication or
the authoritative physical release procedure.

The responder list is an operational participation record, not attendance,
timekeeping, payroll, or shift reporting.

## Support and planned work

Support controls send contextual messages and do not create response records. Station
selection is optional. Planned Engineering work requires an affected selection and
uses distinct text/status while following the same responder and restoration process.

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
