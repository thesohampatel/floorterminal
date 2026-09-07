# Operational sound and accessibility

Sound supplements persistent visual state. It is never a safety alarm, the sole
notification path, or evidence that an external operation succeeded.

## Architecture

Only six internal cue identifiers are accepted. Assets resolve inside the packaged
sound directory and play outside Tk's event loop. Linux prefers `paplay` then `aplay`,
macOS uses `afplay`, and Windows uses `winsound`. Commands use fixed argument arrays,
never a shell. Missing hardware/player and playback errors are sanitized and logged
without blocking the operational workflow. Same-cue cooldown prevents rapid repeats.

## Legal provenance

Every WAV is generated deterministically by `scripts/generate_sound_assets.py` from
mathematical oscillator and envelope definitions. No audio was downloaded; no sample,
voice, recording, trademark sound, or third-party library is embedded. Generator and
outputs are provided under the repository MIT License.

## Settings

- `sound_enabled`: Boolean master switch.
- `sound_volume`: requested volume from 0 through 100.
- `sound_cooldown_ms`: same-cue interval from 0 through 5000 milliseconds.
- **Test sound:** previews a cue without changing workflow state.

`paplay` and `afplay` receive application volume. `winsound` and `aplay` use the OS
mixer level. Commission the actual kiosk output device and system volume.

## Raspberry Pi commissioning

```bash
sudo apt install -y alsa-utils
aplay -l
speaker-test -t sine -f 880 -l 1
aplay src/floorterminal/assets/sounds/response.wav
```

For PipeWire/PulseAudio, provide `paplay` and confirm the kiosk user can access its
session socket. Select the intended HDMI, analog, or USB sink. Test after reboot as
the kiosk user, not only through SSH.

The hardened user service deliberately leaves `PrivateDevices=false` so the
documented `aplay` fallback can use `/dev/snd` when no session audio server exists.
This grants no new permission: access remains limited by the unprivileged kiosk
account's groups and device ACLs. Do not add that account to unrelated device groups.

Keep all visual cues. Assess hearing protection, impairment, ambient noise, nuisance
noise, alarm masking, and safe sound level. Never choose cues confusable with site
fire, evacuation, gas, vehicle, or machine alarms. Disable sound where policy requires.

## Regenerate and verify

```bash
python3 scripts/generate_sound_assets.py
PYTHONPATH=src python3 -m unittest tests.unit.test_audio -v
```

Tests verify the complete asset allow-list, mono 16-bit PCM, 44.1 kHz, short duration,
cooldown, safe command construction, and graceful disabled/backend-failure behavior.
