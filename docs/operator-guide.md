# Operator guide

For independent cells in 1.2.0, see [station groups](station-groups.md).
Touch a running station to report, or a stopped station to reopen its incident.
The action buttons operate on the focused response. Completing it does not release
other active groups. The group overview explains each group's configured impact.

Site safety and escalation procedures always take precedence over this console.

## Display layout in v1.2.2

The interface adapts to your kiosk window automatically. Portrait screens stack
actions; short screens keep the station map and workflow actions together.
Selecting a station opens its optional failure choices and report actions on one
screen. Use station arrows to reach further stations;
**Select whole line** includes all pages.

The feedback band below the header does not cover the line or action buttons.
Tap a progress/notification message to read its full text. Long Information and
error content uses Previous/Next pages; the acknowledgement button stays visible.
On a narrow Settings panel, use Previous/Next beside the category name. Use the
form's large Previous/Next buttons for more fields; optional dragging and wheel
input also work. Save/Cancel remain visible. No configured resolution is
required. [Display behavior and commissioning](adaptive-kiosk.md).

## Screen regions

- **Header:** application/line identity, software update, Information and Settings.
  The clock appears when width allows; connector state and messages use the
  dedicated feedback band in v1.2.0.
  In v1.2.1, a dedicated `HH:MM:SS` card is always visible: in the
  header on wide screens, or beside the feedback band on narrow screens.
- **Status:** redundant face/glyph, text, description, border, color, and motion.
- **Production map:** stations, conveyor, failure selector, whole-line selection.
- **Guidance:** the next valid action for the current workflow state.
- **Primary actions:** unplanned reporting and planned Engineering work.
- **Support:** message-only Engineering, Quality, and Production requests.
- **Notifications:** transient feedback away from controls plus persistent sync state.

## Report an interruption

1. Make the area safe and follow emergency/isolation procedures first when required.
2. Touch an affected station. Its optional failure choices appear as touch cards.
   Larger catalogues offer **Find** and **Back/Next**; selections survive navigation.
3. Optionally touch a reason. **None** clears reasons without deselecting the
   station. **All** selects all reasons. To add stations, choose **Keep selection /
   more stations** and repeat; **Note / more stations** opens the optional Others
   note when applicable. **Deselect station** removes this station from the draft.
4. Read the impact shown at the top, then touch **Report • Engineering** or
   **Start self-fix** for a permitted minor adjustment. These labelled buttons
   are the final reporting confirmation, not a link to another wizard. The
   **Report a problem** button still opens these choices for a saved selection;
   whole-line selection opens them directly without starting the stop itself.
5. Verify the status/timer. A queued badge means local capture succeeded but external
   synchronization is incomplete; do not create a second incident to clear it.

## Record response and completion

For operator-resolved stoppages, follow [Operator self-fix](operator-self-fix.md).
An optional name, the same downtime timer, safe completion, Engineering request
and direct crew arrival are supported without creating another incident. This
is not a shift/check-in feature. The steps below describe Engineering response.

1. A responder opens the highlighted arrival/start action.
2. Touch your **Start work** name tile: it saves immediately. To start with several
   people, first touch **Select several**, choose names, then **Apply**. **Find name**
   filters a large directory by display name or ID; it does not discard a batch selection.
3. Reopen **Update crew**, then touch a **Join** or **Leave** name tile to apply that
   one change immediately. Current crew appear first. Batch editing is still
   available. If everyone leaves, production remains stopped and the downtime
   timer continues; a later responder can join the same incident.
4. After approved inspection, guarding, permits, and production release, touch the
   completion action, then **Confirm • resume**. Confirm the running state and
   final duration. Retry queued synchronization
   only through the explicit action/site outage procedure.

In v1.2.0, local repair and production release do not need to wait for
an external record ID. Supported status, crew, comment, asset and chat operations
are saved in a separate delivery journal and resumed after restart. Touch the
**Delivery** control to open the delivery centre (v1.2.2). Automatic retries honor service
and local budget delays; uncertain writes need administrator review rather than
blind replay. Completion messages describe the local release and queued external
updates without falsely claiming external confirmation. See
[offline reporting and recovery](offline-delivery.md). A queued update is not
permission to skip site communication or the physical release procedure.

If the team directory is unavailable, use the cached list (its age is shown), or
explicitly continue without names and update the crew later. No people are invented
when the directory cannot be fetched.
The list is saved on the kiosk, not fetched on every touch. It refreshes after
midnight when idle; an administrator can use **Settings → Connector → Refresh
team members** sooner (**Connection** on compact screens). Close/reopen an existing picker to see refreshed names;
your active crew is never changed by the refresh itself. [Details](team-roster.md).

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

**v1.2.1:** the three home support shortcuts can be renamed, assigned
different chat/person destinations or hidden in protected Settings → Connector.
Use the label shown on your terminal. These shortcuts do not change incident
assignment, automatic notifications or station/group impact.
[Administrator setup](releases/v1.2.1.md#choose-the-home-screen-support-buttons).

Support controls send contextual messages and do not create response records. If
the connector's request budget is momentarily exhausted, the request is queued and
retried for up to 15 minutes; delivery is not guaranteed. After that it is
retained for administrator acknowledgement as expired in v1.2.0, not delivered
late. Use the site's usual escalation route if help has not arrived. Station
selection is optional. Planned Engineering work requires an affected selection and
uses distinct text/status while following the same responder and restoration process.

Local Production release and external synchronization are separate facts. The
delivery journal does not automatically expire or evict lifecycle updates; a full
journal visibly rejects a new transition and preserves already saved work. Follow
the site's contingency process until delivery is restored. The release time is
captured when **Confirm • resume** is pressed, not when the dialog opens.

## Offline and recovery behavior

Reports are stored before synchronization. Retries preserve the event's idempotency
key. If strict state validation presents a recovery screen, follow the documented
recovery procedure—never delete state merely to force a running display.

**Information** documents version, maintainer/contact route, MIT terms, privacy,
security, safety boundaries, and warranty exclusions. **Settings** requires
administrator authorization and controls stations/failures, workflow, messages,
appearance, sounds, and connector selection/testing. Storage care is automatic;
its latest read-only health snapshot is in System.

In 1.2.0, Settings stays inside the kiosk instead of opening a separate
desktop window, and fills the same kiosk viewport as the main screen. **Save**
applies validated changes; **Cancel** discards unsaved edits (a completed password
change is separate and remains saved). Page long forms with the large Previous/
Next controls, or drag their background/use a mouse wheel. The request budget is
under **Connection**; leave it blank to use the connector's default.

A short ring acknowledges a touch. While an action is underway, the header shows
its name, a spinner and elapsed time; a mouse also shows a busy pointer. Please
wait instead of pressing repeatedly. This indicates processing, not guaranteed
remote delivery. Final success, queued-sync or persistent error feedback tells
you what actually happened. Progress does not cover the station map or step text.

## Software update indicator

The round indicator between the clock and **Information** reports update status:
green when this terminal runs the newest published version, amber when an update
drive is ready or a newer version exists, and red when availability could not be
checked. Nothing about reporting or restoration changes with its colour, and no
version is ever installed without administrator authorization on this screen.

Touch it to see the running version, what that version contains, what a waiting
version changes, and the recorded update history. Follow the
[update guide](update-user-guide.md) to perform an update or a rollback.
