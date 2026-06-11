# Akuvox (Local) — Home Assistant custom integration

A **fully local** Home Assistant integration for Akuvox door phones — built and
tested against the **R20K**, and compatible with other models that share the same
local HTTP API and RTSP server (R20A, R20B, R23, R26, R29, E11/E12, X912/X915, etc.).

No cloud account, no SmartPlus login, no reverse-engineered tokens. It talks
directly to the device on your LAN, so it keeps working offline and never signs
you out of the Akuvox app.

## What you get

After setup, one **device** appears in Home Assistant with these entities:

| Entity | What it does |
| --- | --- |
| **Button: Open Relay A/B/…** | Triggers the door relay (unlocks the door). One per relay you configure. |
| **Lock: Lock A/B/…** | Same relay as a *lock* entity (momentary, auto re-locks) with **open/unlatch** support — works with Assist, HomeKit & Alexa ("unlock/open the front door"). |
| **Camera** | Live RTSP video feed from the door phone. Supports **two-way audio** via go2rtc (see below). |
| **Event: Doorbell** | Fires when the device pushes an Action URL (call, door opened, valid/invalid card, motion…). Use it in automations. |
| **Sensor: Last event / Last card / Last event time** | The most recent event, RFID card code, and timestamp — handy for dashboards & notifications. |
| **Binary sensor: Connectivity** | Shows whether the device is reachable. |

It also provides **device automation triggers** (pick "Front Door — Door opened",
"… — Call", etc. directly in the automation UI) and a service,
**`akuvox_local.open_door`**, for automations.

---

## Supported models & RTSP paths

The integration uses Akuvox's standard local interfaces, so it works with any
model that exposes the `fcgi` open-door API and an RTSP server. Door-opening
**auto-detects** the auth format (standard query-param, High-Security Basic, or
no-auth), so it works whether or not High Security Mode is on.

| Series / model | Open door | RTSP path (default) |
| --- | --- | --- |
| R20K / R20A / R20B / R20 | ✅ | `/live/ch00_0` |
| R23 / R26 / R27 | ✅ | `/live/ch00_0` |
| R29 series | ✅ | `/live/ch00_0` |
| E11 / E12 / E16 | ✅ | `/live/ch00_0` |
| X912 / X915 | ✅ | `/live/ch00_0` |
| C313 / C315 indoor monitors | ✅ (relay if equipped) | `/live/ch00_0` |

If your model uses a different stream path, change it in the setup form (or test
in VLC first: `rtsp://admin:admin@<ip>:554/live/ch00_0`). Some firmwares also
offer a second sub-stream at `/live/ch01_0`.

---

## How it works (the three local mechanisms)

1. **Open door** → HTTP call to the device:
   `http://<ip>/fcgi/do?action=OpenDoor&UserName=…&Password=…&DoorNum=1`
   (`DoorNum` 1/2/3/4 = Relay A/B/C/D). High-security mode is supported too.
2. **Camera** → `rtsp://<ip>:554/live/ch00_0` (the R20K's default RTSP path).
3. **Events** → the device's **Action URL** feature pushes an HTTP request to a
   Home Assistant **webhook** whenever something happens (someone calls, a door
   opens, a card is swiped, etc.).

---

## Installation

### Option A — Manual (simplest)

1. On the machine running Home Assistant, open your config folder (the one with
   `configuration.yaml`).
2. If it doesn't exist, create a folder named `custom_components`.
3. Copy the `custom_components/akuvox_local` folder from this repo into it, so you
   end up with:
   ```
   config/custom_components/akuvox_local/__init__.py
   config/custom_components/akuvox_local/manifest.json
   ... (all the other files)
   ```
4. **Restart Home Assistant.**

### Option B — HACS (custom repository)

1. HACS → **⋮** → **Custom repositories**.
2. Add this repo's URL, category **Integration**, then install.
3. **Restart Home Assistant.**

> Requires Home Assistant **2024.12** or newer and FFmpeg available (it ships with
> Home Assistant OS/Container by default — needed for camera snapshots).

---

## Configure the device (do this once, in the Akuvox web UI)

Log in to the device's web interface in a browser: `http://<device-ip>/`
(default user/password: `admin` / `admin`).

### 1. Enable relay-open over HTTP
**Intercom → Relay → Open Relay via HTTP**: tick **Enabled**. Set a username and
password (or leave blank). These are the credentials you'll enter in Home Assistant.

> If your firmware has **High Security Mode** turned on, note that — there's a
> matching checkbox during Home Assistant setup.

### 2. Enable RTSP (for the camera)
**Intercom → RTSP**: make sure the RTSP server is **enabled** (it is by default).
Default stream path is `/live/ch00_0`.

### 3. Enable Action URLs (for events) — optional but recommended
This is what makes the **Doorbell event** fire in Home Assistant.

- First, finish the Home Assistant setup below and copy your **webhook URL**.
  It looks like: `http://<home-assistant-ip>:8123/api/webhook/XXXXXXXX`
- In the device: **Device Management / Setting → Action URL** → enable it, then
  fill in the events you care about with URLs like:

  | Event | Action URL to enter on the device |
  | --- | --- |
  | Call / button pressed | `http://<ha-ip>:8123/api/webhook/XXXX?event=call&mac=$mac` |
  | Door opened | `http://<ha-ip>:8123/api/webhook/XXXX?event=door_opened&relay=$relay1status` |
  | Valid card | `http://<ha-ip>:8123/api/webhook/XXXX?event=valid_card` |
  | Invalid card | `http://<ha-ip>:8123/api/webhook/XXXX?event=invalid_card` |
  | Motion | `http://<ha-ip>:8123/api/webhook/XXXX?event=motion` |

  The exact set of available Action URL fields varies by model/firmware — fill in
  whichever ones your device offers. The `$mac`, `$relay1status`, `$ip` etc. are
  Akuvox variables the device substitutes automatically.

---

## Add it in Home Assistant

1. **Settings → Devices & Services → Add Integration → “Akuvox (Local)”.**
2. Fill in:
   - **IP address** of the door phone
   - **Name** (e.g. “Front Door”)
   - **Username / Password** (the relay-HTTP credentials from step 1; default admin/admin)
   - **Number of relays** (1 if you only have Relay A)
   - **High Security Mode** — tick only if it's enabled on the device
   - **Add a lock entity per relay** + **auto re-lock delay** (default 5s)
   - **Add the RTSP camera** — leave on unless you don't want video
   - **RTSP path / port** — defaults `/live/ch00_0` and `554` are correct for R20K
   - **RTSP username / password** — *leave blank* to reuse the login above. Fill
     these in **only** if your device uses a separate RTSP/preview account (some
     firmware sets a different stream password from the web-admin password).
   - **Enable two-way audio** + **ONVIF port** — see the Two-way audio section below
3. Submit. The device + entities are created.
4. Open the new device, find its **webhook**: go to
   **Settings → Automations & Scenes → … ** — or simply use the webhook URL shown
   in the device's diagnostics. (The webhook ID is generated automatically; you can
   also find it under Settings → Devices & Services → the integration → the
   automatically created webhook.) Paste that URL into the device's Action URL
   fields as described above.

---

## Using it

### Open the door
- Press the **Open Relay A** button (dashboard, or `button.press`).
- Or call the service in an automation:
  ```yaml
  service: akuvox_local.open_door
  data:
    device_id: <your akuvox device id>
    door_num: 1   # 1=Relay A, 2=Relay B
  ```

### React to the doorbell / events
```yaml
alias: Notify when someone rings the door
trigger:
  - platform: state
    entity_id: event.front_door_doorbell
condition:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.event_type == 'call' }}"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Front door"
      message: "Someone is at the door"
      data:
        image: "/api/camera_proxy/camera.front_door_camera"
```

You can also trigger on the raw bus event `akuvox_local_event`:
```yaml
trigger:
  - platform: event
    event_type: akuvox_local_event
    event_data:
      event: door_opened
```

---

## Two-way audio (talk to visitors) 🎤

The R20K supports **two-way audio over ONVIF**, and Home Assistant can use it
through its built-in **go2rtc**. Plain RTSP only lets you *hear* the visitor —
talking back needs go2rtc's **ONVIF backchannel**.

> Reality check: ONVIF backchannel codec support varies by firmware. This works
> great on many setups; on some it's "hear-only" until you try the RTSP
> backchannel variant below. It's the same mechanism every HA doorbell
> (Reolink, Hikvision, 2N…) uses for talk-back.

**Setup:**

1. In the integration setup (or **Configure**), tick **Enable two-way audio**
   and set the **ONVIF port** (usually `80` on Akuvox; check
   *Device → ONVIF* in the web UI).
2. After enabling, Home Assistant shows a **notification with a ready-to-paste
   `go2rtc.yaml` snippet** filled in with your device's IP, credentials and
   ports — something like:
   ```yaml
   streams:
     akuvox_front_door:
       - rtsp://admin:admin@192.168.1.50:554/live/ch00_0#backchannel=0
       - "onvif://admin:admin@192.168.1.50:80?unicast=true&proto=Onvif"
   ```
3. Paste it into your go2rtc config and restart go2rtc (or the AlexxIT/WebRTC
   add-on).
4. Add a dashboard card pointing at the `akuvox_<name>` stream — the
   [Advanced Camera Card](https://github.com/dermotduffy/advanced-camera-card)
   or [WebRTC Camera](https://github.com/AlexxIT/WebRTC) — and use its
   **microphone button** to talk.

**If you can hear but not talk**, your firmware may prefer the RTSP backchannel.
Replace the ONVIF line with:
```yaml
   - "ffmpeg:akuvox_front_door#backchannel=1"
```
or append `#backchannel=1` to the RTSP source and remove the ONVIF line. Test in
the go2rtc web UI (Streams → links → "two-way audio") before wiring up the card.

**Bonus — TTS / announcements to the door speaker:** once the backchannel works,
install the [AlexxIT/WebRTC](https://github.com/AlexxIT/WebRTC) integration to get
a `media_player` you can target with `tts.speak` or `media_player.play_media`.

---

## Troubleshooting

- **Button errors / “Failed to open door”** → wrong credentials, or High Security
  Mode mismatch. Re-check the relay-HTTP settings in the device web UI, then edit
  the integration via **Configure** (gear icon) to update.
- **“Could not reach the device” at setup** → enter just the IP (e.g.
  `192.168.1.50`), not a full `http://…` URL — though the integration now strips
  that for you. It tries **HTTP first, then HTTPS** (self-signed certs are
  accepted), so HTTPS-only firmware works too. If it still fails, confirm Home
  Assistant and the door phone are on the same VLAN/subnet and nothing is
  blocking port 80/443.
- **Camera black/unavailable** → confirm RTSP is enabled and the path is
  `/live/ch00_0`. Test the URL in VLC: `rtsp://admin:admin@<ip>:554/live/ch00_0`.
  If the stream needs a different password than the web login, set the
  **RTSP username / password** fields under **Configure** (gear icon).
- **No events** → the Action URL must point at the exact webhook URL, reachable
  from the device. Make sure the device and Home Assistant can talk on port 8123,
  and that you used `http://` (not https) unless you have TLS set up.
- **Connectivity sensor off** → the device isn't reachable on port 80 from Home
  Assistant; check the IP/VLAN/firewall.

---

## Publishing this to GitHub for HACS (custom repository)

This repo is already structured the way HACS expects:

```
<repo root>/
├── hacs.json                          # HACS metadata (name, min HA version)
├── README.md
├── LICENSE
├── .github/workflows/validate.yml     # runs hassfest + HACS validation on push
└── custom_components/
    └── akuvox_local/                  # the integration (exactly one folder here)
        ├── manifest.json, __init__.py, api.py, …
        └── translations/en.json
```

**Before you push, do these 4 things:**

1. **Replace the placeholders** (otherwise hassfest passes, but the links/owner
   are wrong):
   - In `custom_components/akuvox_local/manifest.json`: set `codeowners` to your
     GitHub handle (e.g. `["@janedoe"]`) and update `documentation` /
     `issue_tracker` to your repo URL.
   - In `LICENSE`: put your name in the copyright line.
2. **Create the GitHub repo** and push everything at the repo root (the folder
   that contains `hacs.json`, **not** a parent folder).
3. **Publish a release** (e.g. tag `v1.0.0` → *Create release*). HACS uses the
   latest release tag as the version; without a release it falls back to the
   default branch.
4. *(Optional, only required if you later submit to the HACS **default** store)*
   add your brand icon to [home-assistant/brands](https://github.com/home-assistant/brands).
   It is **not** required for installing as a custom repository.

**Then anyone can install it:** HACS → ⋮ → *Custom repositories* → paste the repo
URL, category *Integration* → install → restart Home Assistant.

The included GitHub Action runs **hassfest** and the **HACS validator** on every
push, so you'll immediately see a green check (or what to fix) in the *Actions*
tab. Add badges to the top of this README if you like:

```markdown
![Validate](https://github.com/yourusername/akuvox_local/actions/workflows/validate.yml/badge.svg)
```

---

## Disclaimer

Not affiliated with or endorsed by Akuvox. Community project, provided as-is.
Uses the device's own documented local HTTP API, RTSP server, and Action URL
feature.
