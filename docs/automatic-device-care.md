# Automatic device care — v1.2.0

There are no operator-adjustable log-level, retention or disk-reserve controls.
**Settings → System → Automatic device care** shows the latest background snapshot.
Reopen Settings to refresh that snapshot. No administrator action is needed for
normal cleanup; a warning still requires attention to a full or failing device.

## What the background worker does

One worker starts shortly after launch and checks about once a minute. A previous
check must finish before another begins. It never takes the operator-action busy
lock, calls a provider, changes machine state, or touches Tk from the worker.

It measures the filesystem containing the log directory, inventories only known
dated audit files, adjusts retention, removes eligible older segments, and reports
free space. On Linux, available memory and the standard thermal sensor are read
when present. Missing sensors on other systems are normal, not startup failures.
Low free space, unavailable checks, current audit-write failures, newly low memory
or high temperature produce non-blocking feedback. The System page includes audit
queue-overflow/write-failure counters since launch.

Worker-start failures and unexpected inspection errors release the single-job
guard, expose a device-care warning and allow the next scheduled retry. Shutdown
does not start a new check. None of these failures acquires the workflow busy lock.

| Automatic policy | Bound |
| --- | --- |
| Maximum audit age | 183 calendar dates including today; shorter under pressure |
| Log budget | At most 2% of filesystem size, capped at 512 MiB, and limited by space above reserve |
| OS reserve target | 5% of filesystem size, clamped between 256 MiB and 2 GiB |
| Growth estimate | Observed bytes per logged date, at least 64 KiB/day, plus 50% headroom |
| Current-day rotation | Four segments of up to 4 MiB each; oldest segment replaced first |
| Per-record size | 64 KiB; oversized detail is replaced by an explicit omission notice |
| Pending audit writes | At most 1,024 encoded records / 64 MiB of payload, plus bounded object overhead |
| Inventory work | At most 12,000 entries; an abnormal tree stops cleanup and reports a check failure |

This estimates capacity; it cannot guarantee six months of logs. A full disk,
other applications, faulty flash, clock changes or unusually high activity can
shorten available history. Today's segments are not removed by age/pressure
cleanup; rotation bounds them separately. Future-dated files are retained until
the clock catches up, to avoid deleting a potentially active file after a clock
correction. Maintain accurate system time.

Memory warnings mean available Linux memory is below 64 MiB or 5% of total,
whichever is larger. Temperature warnings begin at 80 °C when that sensor exists.
These are advisory observations, not hardware certification, safety alarms, a
process supervisor or an automatic shutdown/reboot policy.

## Exactly what may be deleted

The audit-log worker only cleans these application-owned paths:

```text
logs/YYYY/MM/DD/activity.jsonl
logs/YYYY/MM/DD/activity.1.jsonl
logs/YYYY/MM/DD/activity.2.jsonl
logs/YYYY/MM/DD/activity.3.jsonl
```

Eligible closed-day logs are removed oldest first. Empty date folders may then
be removed. Unknown files remain, even inside an expired date folder. Directory
and file symlinks are not followed. Permissions are repaired to owner-private
where the platform supports them. Already-private permissions are left unchanged,
avoiding repeated permission metadata writes on flash storage.
Already-private segments are not reopened during permission maintenance, and
shared date directories are inspected only once per pass.
Hard-linked audit files are excluded from repair and cleanup. Appends and rotation
reject nonregular or linked files; a named pipe cannot block the writer's open.
An affected audit stream reports a write failure while incident recovery remains
independent. Investigate suspicious files rather than deleting recovery data.

Cleanup **never** deletes `response_state.json`, pending deliveries, connector
files, configuration, Settings credentials, update/recovery files or backups.
The existing state/journal limits still apply independently: a full journal
rejects a new transition visibly rather than discarding an already saved report.

## Separate incident archive

The local reporting archive is not a diagnostic log. Its separate background
worker retains open records and pending-delivery records, limits cleanup to
eligible completed incidents, and adjusts its storage budget without operator
settings. See [local history](local-history.md#automatic-retention) for the
730-day maximum, pressure-driven policy, private database and recovery bounds.
The System page shows the latest archive maintenance snapshot separately from
audit-log health; neither is a guarantee of regulatory retention or a backup.
Maintenance-only archive results update that snapshot without taking the
operator-action lock or rewriting incident state. Batches containing incident
records or remote-ID links still require the existing durable acknowledgement;
pending records arriving during maintenance are left for the next batch.

## Audit availability versus incident durability

The live kiosk has one asynchronous audit writer. A slow log device cannot block
touch handling. Under extreme load an audit queue may overflow; counters and a
recovery gap record make this visible. Normal shutdown allows a bounded flush;
power loss or forced termination can lose unflushed audit entries. Logs are
best-effort diagnostics, **not** a tamper-proof or legally complete archive.

Incident state and its delivery journal are still saved atomically through the
separate durable state store before the UI reports a transition as saved. Failed
incident persistence restores the last saved state and shows a persistent error.
Audit success is never used as proof of incident persistence or remote delivery.
If a site needs longer/compliance retention, arrange a separately governed archive
with appropriate privacy, backup and access controls; do not rely on kiosk logs.

## Existing installations

The existing `log_directory` remains recognized so historic files stay in place.
It is not editable in the kiosk. Legacy `log_level`, `log_retention_days`,
`log_storage_reserve_mb` and `log_daily_growth_floor_mb` values are accepted for
migration but ignored by device care and omitted on the next configuration save.
INFO and higher events are retained subject to the automatic bounds. A pre-existing
retention setting longer than 183 days does not exempt older logs from cleanup.

Tests cover low space, file ownership, symlinks, rotation, bounded queues, failed
writes and unavailable sensors. See [verification](verification.md). Physical
storage failure, thermal behaviour and a multi-day site soak remain commissioning
requirements, not guarantees supplied by an offline test.
