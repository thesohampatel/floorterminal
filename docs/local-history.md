# Local reporting history and standalone use

**1.2.0.** Incident records are retained locally whether the configured
external system is available, unavailable or absent. This archive is separate from
shorter-lived diagnostic logs and from the recovery/delivery journal.

## Reporting modes

**Settings → General → Reporting mode**:

- `connected` (default): transitions are recorded locally and supported external
  work is queued. An outage or missing connector does not switch the terminal
  into a data-discarding mode. Pending deliveries remain visible until sent or
  reconciled; capacity is bounded.
- `local`: deliberate standalone operation. Incidents, fault reasons, timers,
  operator self-fix/handover, unnamed Engineering response and planned work can
  complete without a connector. No external delivery jobs are created. Directory
  names and chat calls are unavailable rather than fabricated. A configured
  connector is not automatically activated in this mode.

Finish active incidents and deliver/reconcile pending external work before
changing modes through Settings. Selecting local mode is **not** a way to erase a
failed delivery. Completed standalone records are not automatically uploaded when
switching back to connected mode; bulk export/backfill is a future reporting
feature, not an undocumented replay of historical notifications.

## Files and security

The archive is **`records/incidents.sqlite3` inside the runtime data directory**,
alongside `response_state.json` and `config.json`. For a source run this is normally
the project runtime directory; installed/updated deployments use their existing
persistent runtime root, not a version-specific application directory.

On POSIX systems the directory is owner-only (`0700`) and the database is owner
read/write (`0600`). Symlink and hard-linked/nonregular database files are rejected.
The database uses parameterized SQL, a schema version, full synchronous commits,
transactional upserts and bounded reads. Corrupt or unsupported archives are not
silently replaced. An archive failure keeps records in recovery state and raises a
visible warning.

This is **access-controlled storage, not encrypted storage**. The administrator
must provide OS account protection, disk encryption where required, protected
backups and a privacy policy for any recorded names/notes. A compromised OS or SD
card remains outside the application's trust boundary. Do not write credentials,
personal secrets or unrelated sensitive details into operator notes.

`records/`, database files and their sidecars are excluded from Git. Publication
and release audits reject them. The build contains no site's incident archive.
Preserve this directory together with the recovery state when moving a kiosk.

## What is kept

One record per stable incident UUID, including:

- Line identity; selected fault stations; expanded affected stations and groups;
  impact rule and frozen external routing IDs (no connector credentials or URLs).
- Fault choices and notes; response category; planned work type/label.
- Original start, work start, escalation, operator request/handover and confirmed
  completion timestamps; final elapsed/active-work seconds and duration class.
- Active and historical crew participation, including joins and departures.
- Local response reference and a separately reconciled remote record ID if it
  arrives after local completion.

`completed_at: null` means still open. A non-null value means completed; `status`
records the workflow phase immediately before completion. The archive stores the
latest incident snapshot, including its participation timeline—not every touch,
animation frame or audit message. Diagnostic details remain in `logs/` under the
separate automatic log policy.

## Durability and responsiveness

1. StateStore commits the incident transition, external delivery intents and a
   pending archive snapshot together before acknowledging the operator action.
2. One background worker writes at most 32 staged incident snapshots per batch.
   SQLite writes, retention scans and incremental space reclamation do not run
   in the renderer or Tk event loop.
3. A successful archive write is acknowledged through the existing serialized
   local-operation worker. A slow SD-card fsync cannot freeze animation. A newer
   snapshot is not removed by an older acknowledgement.
4. A restart between archive commit and acknowledgement safely replays the same
   UUID. An outage of the external system does not delay local archival.

If the outer state-file commit fails after SQLite accepted a batch, the writer
retains that acknowledgement and retries the local commit after five seconds.
It does not remain permanently busy or require a restart. Temporary worker-creation
failures also leave staged records intact and retry through the normal backoff.

Staging is bounded at 256 snapshots / 8 MiB, with a 128 KiB per-record ceiling.
These are recovery safety limits. If storage stays broken and the queue fills,
the next transition is rejected and rolled back with an error; unsaved production
changes are never displayed as successfully recorded. Restore storage and follow
the site's manual incident procedure. A kiosk cannot guarantee durable writes to
a failed or full storage device.

## Automatic retention

No operator retention setting is needed. Background care:

- Reserves 5% of filesystem capacity for the OS, bounded between 256 MiB and 2 GiB.
- Budgets the archive at up to 2% of the filesystem, at most 512 MiB, further
  constrained by free space above that reserve.
- Deletes completed records older than 730 days during normal maintenance.
- Under storage pressure, reclaims the oldest completed records older than 24
  hours. It never deletes open records, today's completions, recovery state or
  external delivery jobs. Records with pending external jobs are protected.
- Deletes at most 200 eligible records per pass and incrementally reclaims SQLite
  pages. Maintenance is hourly, independent of screen activity; no full database
  vacuum blocks the operator screen.

Protected data can legitimately exceed the target budget; it is not silently
discarded to satisfy a quota. Settings → System shows archive health and pending
storage work. Hardware capacity, usage and storage speed determine effective
retention. This is not a regulatory retention guarantee or a backup service.

## Future reporting / backup boundary

The versioned database is a stable local source for subsequent reporting work.
The internal `IncidentArchive.recent(limit)` API returns up to 1,000 records with
late external IDs resolved. A kiosk reporting dashboard, CSV export and automatic
remote backfill are not included in this change. For consistent backups, stop the
application or use SQLite's backup facility; do not copy a database mid-write and
assume it is a valid backup. Restore/archive investigation should be performed by
an authorized administrator, never by editing the live SQLite file in place.
