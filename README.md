# VIGIL
### Multi-Sensor Awareness Platform

> LIMINAL · AMPLIFY · NIGHT VISION — unified under one shell.

## Modules

| Module | Function | Sensors |
|---|---|---|
| **Liminal** | Hidden door / structural anomaly detection | Camera (env), Microphone, Magnetometer |
| **Amplify** | Production audio DSP with noise gate | Microphone |
| **Night Vision** | 6-palette NVG camera with motion detection | Camera (env) |

## Stack
- Vanilla ES modules — zero build step
- PWA + Service Worker
- AudioWorklet (Blob URL, no bundler required)
- MediaStream arbitration — no permission conflicts between modules
- RAF arbitration — no competing render loops

## Deploy
```bash
vercel deploy --prod
```

## Architecture
Each module exports `{ init(container), destroy(), health() }`.  
Shell lazy-loads on tab activation, calls `destroy()` + releases MediaStreams on tab leave.  
Telemetry polls `health()` every 5s → drives header status dot.

## Repo
`cloudygetty-ai/vigil`
