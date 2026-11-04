# Configuration reference

For software upgrades/downgrades, see [data compatibility](update-data-compatibility.md).
The current reader adapts known defaults/aliases in memory; Settings retains unknown
extensions already saved. Unsupported future schemas are refused, not reset.

`config.json` is deployment-owned runtime data. Create it from the tracked neutral
example with `python3 scripts/setup_runtime.py`, keep it owner-private, and never
commit it. Protected Settings uses the same validation and atomic write path.

## Line model

- `reporting_mode`: `connected` (durable external delivery) or `local`
  (standalone, no external jobs). See [local history](local-history.md).
- `station_groups`: optional partition into named groups with stable `id`,
  `stations` and `stop_scope` (`group` or `line`). Empty means a continuous line.
  See [group setup, behaviour and mapping](station-groups.md).
- `line_name`: display name.
- `zones`: unique station names in sequence order; names are arbitrary. With
  explicit groups, the map places group members together, preserving their
  relative order. The group overview exposes every group through touch paging.
- `station_failure_types`: exactly one key for every `zones` entry and no unknown
  keys. Each value is a list of unique, nonempty, printable custom choices. `[]`
  means **Others only**. There is no fixed count limit. The UI always adds exactly
  one **Others**; do not put it in the custom list. Existing file-size safeguards
  apply. [Editor, search and selection details](failure-reasons.md).
- `location_id`, `asset_id`: opaque external identifiers used only by enabled mappings.

Failure selection remains optional. Choose observable terms that assist response
without forcing operators to make an unsupported diagnosis.

## Workflow and destinations

Timing values control escalation, micro-stop classification, animation, and refresh
behavior and are bounded by validation. Team/conversation values are deployment
labels resolved through connector mappings. Templates accept documented placeholders
only and never execute expressions. Test output in an authorized non-production area.

- `engineering_team_name`: exact external directory team used for responder lookup
  and assignment when those capabilities are enabled.
- Team, chat, and person names are free text of at most 120 characters on one
  line. In Settings they can always be typed; when the connected directory is
  available its names are offered as suggestions. A name that the loaded directory
  does not contain is saved, logged, and reported after saving, because a directory
  may be paged or not yet contain a newly created chat. Matching ignores letter case.
- `engineering_chat_name`, `quality_chat_name`, `production_chat_name`: destinations
  for the three support controls.
- `common_activity_chat_name`: optional shared lifecycle destination.
- `escalation_chat_name`: optional escalation-only destination; if blank, escalation
  uses Engineering and common activity destinations.
- `response_record_priority`, `response_record_type`, `planned_work_priority`:
  canonical values translated by `connector.json`.
- `asset_status_tracking`: sends unavailable/available asset transitions only when
  both an asset identifier and the connector capability are present. Each status
  carries a note listing the affected stations, the reported failure types, the
  operator's own **Others** description, and the response-record reference; the
  Online note also states the classification and elapsed time (affected-group
  time for a partial stop, total line time for a whole-line stop). It is sent
  through the connector's `status_description` field mapping.
- `directory_max_pages`: 1–20, default 3. Bounds cursor pagination for every team,
  member, user, and conversation lookup. Each page consumes one request from the
  configured application-wide rolling-minute budget.
- `escalation_minutes`: 0–1440; zero disables the one-time unanswered-event message.
- `micro_stop_threshold_minutes`: 1–1440, used only for completion classification.

### Application API budget (1.2.0)

Open password-protected **Settings → Connector → Requests per minute**, enter a
positive whole number (for example `25`), then **Save**. The category is labeled
**Connection** on compact layouts. No rebuild is needed.

```json
"api_requests_per_minute": 25
```

Blank in Settings, or `null`/an absent field in `config.json`, inherits
`connection.requests_per_minute` from the active connector. The neutral connector
starts at `10`; it is a default, **not a maximum**. Zero, negatives, booleans and
fractions are rejected; there is no unlimited sentinel. Choose a budget within
your service agreement, accounting for other applications using the same account.

The budget counts attempted HTTP requests (including directory pages, retries and
Settings diagnostics) within a rolling 60-second window, not a wall-clock minute.
Saving Settings or switching connectors does not clear consumed requests. Lowering
the limit below recent usage pauses further calls until enough requests expire.
The window is process-local and restarts empty after application restart. Queued
workflow updates keep their persisted retry deadlines and idempotency protections.
The v1.2.0 delivery worker uses one request attempt per scheduled operation rather
than sleeping through inline retries. Shared service cooldowns prevent a backlog
from repeatedly probing an unavailable service. See [offline delivery](offline-delivery.md).

Provider quota headers and HTTP 429/Retry-After remain independent restrictions;
increasing this local setting cannot override them. The 90% shared-quota warning
still describes account-wide usage, not just this terminal's usage.

If rollback compatibility with 1.1.0 is required, keep the connector file's budget
at 10 or less and use the new **Settings override** instead. Older versions reject
connector budgets above 10 and do not implement this override. Recheck the intended
request budget after any rollback.

Message templates may use only `{line}`, `{zones}`, `{timestamp}`, `{time}`,
`{department}`, `{condition}`, and `{work_label}`. A template may use the subset
that makes sense for it; unknown placeholders and malformed braces stop startup.

## Sound

```json
"sound_enabled": true,
"sound_volume": 70,
"sound_cooldown_ms": 750
```

Volume is 0–100 and cooldown 0–5000 ms. See [sound](sound.md).

## Software updates

```json
"software_update_check_enabled": true
```

The only update-related setting. It controls whether the terminal opens a network
connection to the fixed release endpoint to learn whether a newer version exists.
Set it to `false` for air-gapped sites; the update indicator then shows amber with
an explanation instead of red.

The release endpoint, the trusted signing keys, the accepted USB volume labels, and
every safety bound are compiled into the build and cannot be changed by
configuration, environment variable, or removable media. See
[offline software updates](software-updates.md).

## Appearance, storage, and logs

Fullscreen, animation, accessible palette, and locale settings are validated. Screen
geometry is computed at runtime; there is no fixed configured resolution. Validate
touch target sizes on the commissioned physical screen.

v1.2.0 reflows landscape/portrait content automatically. No width, height, panel
model or station-count preset is needed in `config.json`. A usable window is at
least 320×400 logical units; smaller windows show a resize/rotate message rather
than exposing overlapping controls. This is a usability floor, not a fixed design
resolution. See [adaptive kiosk behavior](adaptive-kiosk.md).

Logs use `logs/YYYY/MM/DD/activity.jsonl` plus bounded rotated segments. Background
device care automatically chooses an audit budget and retention up to 183 days,
shortening history under space pressure. No tuning is exposed in Settings.
Incident recovery and pending reports are never housekeeping targets. Protect
operational records and apply site privacy policy. Credentials and external response
bodies are not logging fields. See [automatic device care](automatic-device-care.md).

- `fullscreen_on_linux`: requests kiosk fullscreen after the first rendered frame.
- `animation_interval_ms`: 30–1000 ms; new installations default to 33 ms (about
  30 frames/second). Existing values, including 80 ms, are preserved. Set 33 in
  Settings → System for smoother motion after upgrading. Slow frames never queue
  catch-up bursts, and obscured screens update less frequently.
- `ui_language`: installed locale key; v1.2.0 ships and verifies the English interface.
- `ui_color_preset`: `standard`, `colorblind_safe`, or `custom`.
- `ui_colors`: exact six-digit colors for background, cards, text, muted text,
  status colors, and borders. Contrast checks in Settings reject unsafe choices.
- `log_directory`: preserved deployment path; not editable from the kiosk.
- Legacy `log_level`, `log_retention_days`, `log_storage_reserve_mb` and
  `log_daily_growth_floor_mb` are ignored by v1.2.0 device care and omitted on save.
  Existing installations need no manual configuration migration.

The complete authoritative schema example is
[`config.example.json`](../config.example.json). Startup rejects wrong types,
out-of-range values, missing/extra failure mappings, malformed colors, unsafe paths,
and invalid templates instead of displaying misleading state.

## Ownership and secret separation

```bash
chown kiosk-user:kiosk-user config.json connector.json
chmod 600 config.json connector.json
```

Do not put connector secrets or the Settings password in `config.json`. Connector
credentials belong in the ignored deployment connector (or an approved injection
process). The public initial Settings password is `admin@123`. Change it in
Settings → System, not in `config.json`. Local changes save only a salted PBKDF2
verifier in ignored, owner-private `settings_auth.json`. Preserve that file during
backups/upgrades; never include it in a release. See [Settings access](settings-access.md).
