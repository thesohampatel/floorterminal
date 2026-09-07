# Configuration reference

`config.json` is deployment-owned runtime data. Create it from the tracked neutral
example with `python3 scripts/setup_runtime.py`, keep it owner-private, and never
commit it. Protected Settings uses the same validation and atomic write path.

## Line model

- `line_name`: display name.
- `zones`: unique station names in left-to-right flow order; names are arbitrary.
- `station_failure_types`: exactly one key for every `zones` entry and no unknown
  keys. Each value contains one to four unique, nonempty custom choices. The UI adds
  **Others** automatically as choice five, so it must not appear in this object.
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
- `engineering_chat_name`, `quality_chat_name`, `production_chat_name`: destinations
  for the three support controls.
- `common_activity_chat_name`: optional shared lifecycle destination.
- `escalation_chat_name`: optional escalation-only destination; if blank, escalation
  uses Engineering and common activity destinations.
- `response_record_priority`, `response_record_type`, `planned_work_priority`:
  canonical values translated by `connector.json`.
- `asset_status_tracking`: sends unavailable/available asset transitions only when
  both an asset identifier and the connector capability are present.
- `directory_max_pages`: 1–20, default 3. Bounds cursor pagination for every team,
  member, user, and conversation lookup. Each page consumes one request from the
  application-wide 10-request rolling-minute ceiling.
- `escalation_minutes`: 0–1440; zero disables the one-time unanswered-event message.
- `micro_stop_threshold_minutes`: 1–1440, used only for completion classification.

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

Logs use `logs/YYYY/MM/DD/activity.jsonl`; retention defaults to six months. Startup
checks minimum free space and estimated log capacity. Protect operational records and
apply site privacy/retention policy. Credentials and external response bodies are not
logging fields.

- `fullscreen_on_linux`: requests kiosk fullscreen after the first rendered frame.
- `animation_interval_ms`: 30–1000 ms; lower values animate more frequently.
- `ui_language`: installed locale key; English is packaged in version 1.0.0.
- `ui_color_preset`: `standard`, `colorblind_safe`, or `custom`.
- `ui_colors`: exact six-digit colors for background, cards, text, muted text,
  status colors, and borders. Contrast checks in Settings reject unsafe choices.
- `log_directory`, `log_level`, `log_retention_days`: log location, minimum severity,
  and retention (1–730 days).
- `log_storage_reserve_mb`, `log_daily_growth_floor_mb`: capacity-model inputs used
  by the six-hour free-space safety check.

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
