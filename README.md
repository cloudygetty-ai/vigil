# VIGIL
### Multi-Sensor Awareness Platform

> Three instruments. One shell. Zero build step.

---

## Modules

| Module | Purpose | Sensors |
|---|---|---|
| **LIMINAL** | Structural anomaly + hidden door detection | Rear camera · Microphone · Magnetometer |
| **AMPLIFY** | Production audio DSP with hysteresis noise gate | Microphone |
| **NIGHT VISION** | 6-palette NVG camera with motion detection | Rear camera |

---

## Architecture

```
vigil/
├── index.html                  ← Shell · tab router · obsidian/gold aesthetic
├── manifest.json               ← PWA manifest
├── sw.js                       ← Service worker (vigil-v1 cache)
├── vercel.json                 ← COOP/COEP headers · Permissions-Policy
└── modules/
    ├── liminal/engine.js       ← Sobel edge · Hough · GLCM · magnetometer · FFT
    ├── amplify/engine.js       ← AudioWorklet noise gate · P25 calibration · waveform
    └── nightvision/engine.js  ← LUT palettes · CLAHE · motion blobs · MediaRecorder
```

**Module contract** — every engine exports:

```js
{ init(container), destroy(), health() }
```

Shell calls `init` on tab activation, `destroy` + MediaStream release on tab leave.
No module holds global state. No competing RAF loops. No permission conflicts.

---

## Stack

- Vanilla ES modules — zero bundler, zero build step
- AudioWorklet via Blob URL — no worker file required
- MediaStream arbitration — camera + mic allocated per module, released on exit
- RAF arbitration — single render loop owner per frame
- PWA + Service Worker — installable, offline shell
- Telemetry — `health()` polled every 5s, drives header status dot

---

## Design System

| Token | Value |
|---|---|
| Background | `#0D0A14` obsidian |
| Accent | `#C9A84C` gold |
| Display font | Cinzel 700 |
| UI font | DM Mono 400 |
| Health: nominal | `#3DBA7A` |
| Health: degraded | `#F5A623` |
| Health: fault | `#E53E3E` |

---

## Deploy

```bash
# Vercel — connect cloudygetty-ai/vigil, framework: Other, root: /
vercel deploy --prod
```

No build command. No install command. Output directory: `.`

`vercel.json` sets `Cross-Origin-Opener-Policy: same-origin` and
`Cross-Origin-Embedder-Policy: require-corp` — required for AudioWorklet
and SharedArrayBuffer on all browsers.

---

## Roadmap

| Priority | Item |
|---|---|
| `P1` | Full Hough accumulation + GLCM texture + magnetometer 3σ + acoustic FFT in LIMINAL |
| `P1` | IndexedDB scan history + result cards UI |
| `P2` | Claude AI vision — frame → Anthropic API → anomaly overlay |
| `P2` | Compass HUD in Night Vision via DeviceOrientation API |
| `P3` | Swipe gesture tab navigation |
| `P3` | PWA install prompt + icon set |

---

## Org

`cloudygetty-ai` · Sentinel Engine v6.0 · ENTROPY-ZERO
