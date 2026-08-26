# VIGIL SENTINEL

**Detect what was put on your phone — via AirDrop, Quick Share, Bluetooth, or WiFi.**

You plug your phone into your computer over USB and run one command. SENTINEL reads
the phone's real state, compares it against a known-good baseline you recorded
earlier, and tells you exactly what appeared in between.

---

## Read this first — what is and isn't possible

Most "phone virus scanner" apps are theatre. An app on your phone **cannot** scan
your phone. iOS and Android sandbox every app: it can read its own storage and
nothing else. No app in the App Store or Play Store can see an AirDropped file
sitting in another app's container, and any app claiming a full-device intrusion
scan is showing you an animation.

Reading device state genuinely requires talking to the phone from *outside* — over
USB, through the debugging and device-management interfaces Apple and Google
actually expose. That is what this tool does.

Its limits are stated honestly:

| | Android | iOS |
|---|---|---|
| Installed apps + install source | full | full |
| Sideloaded / non-store apps | full | full (signer identity) |
| Files in transfer folders | full (`/sdcard/Download`, `Bluetooth`, …) | **camera roll only** |
| Configuration profiles / MDM | device admins, fully | partial — manual step provided |
| Live AirDrop transfer log | n/a | yes (`--watch`) |
| Network interception | yes | yes |

**The one hard iOS limit:** an AirDropped file the user saved into an app
(Files, Notes, a messenger) lives in that app's container. Apple exposes no
interface to enumerate it — not to this tool, not to any tool, not to an on-device
app. What a payload *cannot* hide is the configuration profile, app signature, or
`sharingd` log entry it needs to actually do anything. That is what SENTINEL hunts.

---

## Install

No packages, no build. Python 3.9+ and the platform tool for your phone.

```bash
git clone https://github.com/cloudygetty-ai/vigil
cd vigil/sentinel
```

**For Android:**
```bash
brew install android-platform-tools      # macOS
sudo apt install android-tools-adb       # Debian/Ubuntu
```

**For iPhone:**
```bash
brew install libimobiledevice ideviceinstaller          # macOS
sudo apt install libimobiledevice-utils ideviceinstaller # Debian/Ubuntu
```

`sentinel` runs without either installed — it just scans the network and tells you
which backend is missing.

---

## Prepare the phone

**Android** — Settings → About phone → tap *Build number* seven times → back to
Settings → Developer options → **USB debugging** on. Plug in, accept the prompt.

**iPhone** — plug in, unlock, tap **Trust This Computer**.

```bash
./sentinel devices
```

---

## Use it

### 1. Record a baseline while you believe the phone is clean

```bash
./sentinel scan --baseline
```

This is the step that makes everything else work. Do it now, before you need it.

### 2. Scan again whenever you're suspicious

```bash
./sentinel scan
```

The report opens with **Changes since baseline** — every app, file, profile and
security setting that appeared, vanished or changed since. A new app you didn't
install, or a new file in Downloads you didn't download, is not a heuristic guess.
It's a fact.

### 3. Catch AirDrop in the act (iPhone)

```bash
./sentinel scan --watch 60
```

Watches `sharingd`, the iOS daemon behind AirDrop, for a minute. Leave the phone on
the table. Transfers you didn't accept mean someone nearby is pushing at it.

### 4. Save a report

```bash
./sentinel scan --html report.html     # standalone page, opens in any browser
./sentinel scan --json findings.json   # machine-readable
```

---

## Options

| Flag | Effect |
|---|---|
| `--baseline` | Record this scan as the known-good reference |
| `--watch N` | iOS: watch the device log for AirDrop activity for N seconds |
| `--window H` | How far back a file counts as "recent" (default 72h) |
| `--device SERIAL` | Target one phone when several are attached |
| `--network-only` | Skip the phone; check the WiFi only |
| `--no-network` | Skip the network probes |
| `--all` | Show passing checks too, not just problems |
| `--html PATH` / `--json PATH` | Write a report |

Exit codes: `0` clean · `1` harden · `2` suspicious · `3` compromised — so you can
run it from a cron job or a shell script.

---

## What it checks

**Delivery — how something got on**
- Wireless debugging (`adb_wifi_enabled`, `service.adb.tcp.port`) — the cleanest way
  to push an app onto a phone over WiFi, silently, from anywhere on the network
- APKs, scripts and `.mobileconfig` files sitting in Downloads and Bluetooth folders
- Everything new in transfer folders since your baseline
- iOS: live `sharingd` AirDrop transfer log
- iOS: trusted-computer pairing hygiene

**Persistence — what stayed behind**
- Apps not installed from any app store, with install timestamps and granted permissions
- iOS apps not carrying an App Store signature (developer / enterprise sideloads)
- iOS provisioning and configuration profiles
- Device administrators — how stalkerware blocks its own uninstall
- MDM supervision

**Surveillance — what can watch you**
- Accessibility services — reads every screen, types on your behalf. The single most
  abused Android spyware surface
- Notification listeners — sees message previews and 2FA codes

**Network — interception**
- ARP table collisions (one MAC claiming several IPs = ARP spoofing)
- Default gateway MAC changes = evil-twin access point
- DNS rewriting, against an answer that's fixed worldwide
- TLS interception — certificate issuer checked against public CAs and known
  interception appliances (mitmproxy, Burp, Zscaler, Fortinet, …)
- Global HTTP proxy and VPN tunnels configured on the phone

**Integrity — is the OS trustworthy at all**
- Bootloader lock state and verified boot
- Root binaries
- iOS: crashes in `sharingd`, BlastDoor, WebKit and `imagent` — where a failed
  exploit against an AirDropped or messaged payload shows up

Every finding prints the raw command output it was drawn from. Nothing is
unfalsifiable — you can always check the tool's work.

---

## Harden against the next attempt

**iPhone** — Settings → General → AirDrop → **Receiving Off** or *Contacts Only*.
Settings → General → VPN & Device Management: every entry should be one you added.
Settings → General → Transfer or Reset → Reset → **Reset Location & Privacy** revokes
every trusted-computer pairing at once.

**Android** — Settings → Google → Devices & sharing → Quick Share → **Hidden from
everyone** when not in use. Developer options **off**. Settings → Security → Install
unknown apps: revoke for every app.

**Both** — Bluetooth off when you're not using it. A device name that isn't your
real name.

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

28 tests, no phone required — the device probes run against canned `adb` output.

---

## Design

```
sentinel/
├── sentinel                    ← launcher, no install step
└── vigil_sentinel/
    ├── shell.py                ← subprocess + tool discovery; failures are values
    ├── devices.py              ← USB discovery for both platforms
    ├── findings.py             ← Finding model, severity, threat scoring
    ├── baseline.py             ← snapshot + diff (the core detector)
    ├── report.py               ← ANSI terminal + standalone HTML
    ├── cli.py                  ← argparse entry point
    └── probes/
        ├── android.py          ← 9 probes over adb
        ├── ios.py              ← 7 probes over lockdown
        └── network.py          ← 3 host-side probes
```

Probes never raise into the runner: a failing probe becomes a reported gap, so a
missing tool or a wedged device degrades the scan instead of aborting it. Serials
are hashed before they're used as snapshot filenames.

---

`cloudygetty-ai/vigil` · SENTINEL v1.0
