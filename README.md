# VIGIL
### Multi-Sensor Awareness Platform

> LIMINAL · AMPLIFY · NIGHT VISION · DUAL CAM — every feature, one shell.

---

## HOW TO OPERATE

### LIMINAL — Hidden Door Detection

**Setup**
1. Open VIGIL → tap **LIMINAL** tab
2. Tap **ACTIVATE CAMERA SCAN** — grant camera + microphone access
3. Stand 3–6 ft from a suspect wall. Fill the frame floor to ceiling.

**Scanning**
- **SCAN THIS SURFACE** — captures the frame and runs the full pipeline
- **FRAMES selector** (1×/3×/5×) — multi-frame median stacking; use 3× or 5× in low light for noise reduction
- **DIST selector** (3ft/6ft/10ft/15ft) — calibrates Sobel edge threshold by distance; always match your actual standoff
- **BASELINE** — first scan a plain known-good wall. All subsequent scans are compared against it, boosting accuracy

**Camera controls**
| Control | Function |
|---|---|
| Pinch / Zoom slider | 1×–10× optical zoom |
| Tap viewport | Tap-to-focus with ring indicator |
| 🔦 Torch | Hardware torch on rear camera |
| 🌙 Night Mode | Increases brightness + contrast for dark surfaces |
| ⏸ Freeze | Locks frame — scan from still image |
| ⛶ Fullscreen | Full-screen camera with floating controls |
| 🔬 Macro | Sets zoom to 5× for hardware/seam detail |
| ⊞ Grid | Overlay composition grid |
| ↺ Flip | Switches front/rear camera |
| 📊 Luma | Exposure meter on right edge |
| ⊞ SESSION | Multi-wall mode — scans all 4 walls in sequence |

**Reading results**
- **Ring percentage** — hidden door probability (pixel engine + Claude AI blended)
- **Confidence interval** — e.g. `42–68% (3f)` — narrows with more frames
- **MARKS view** — annotated hotspots on your capture. Larger ring = higher confidence
- **EDGES view** — raw Sobel output. A true door seam = strong continuous vertical line
- **LINES view** — Hough accumulator. Red column = dominant vertical seam candidate
- **Signal grid** — 6 raw metrics: Edge Density, Vert Seams, Hough Seam, GLCM Contrast, Symmetry Break, Baseline Diff
- **Zone analysis** — floor/ceiling/trim/wall/corners scored 0–100
- **Anomaly cards** — HIGH/MEDIUM/LOW confidence findings with detail
- **Door Location** — predicted door type, exact wall position, how to open, what's behind it

**AI Vision** (requires Anthropic API key in the app)
- Fires automatically after every scan
- Analyzes the frame visually, confirms or overrides pixel score
- Shows findings with exact pixel coordinates and actionable steps
- Pixel score and AI score are blended 45%/55%

**Sensors**
| Sensor | How to use |
|---|---|
| **Magnetometer** | Tap START SCAN. Hold phone still for baseline (2–3 sec). Slowly sweep horizontally at waist height along the wall. A spike = ferrous metal (hinge, strike plate, catch). Uses 3-sigma dynamic threshold |
| **Acoustic FFT** | Tap SET REF WALL first — knock on a known solid wall to save reference spectrum. Then tap START MIC. Knock firmly in a grid pattern on the suspect surface. Low-freq dominant FFT = HOLLOW DETECTED. Cross-correlates against reference spectrum |

**Manual Checklist**
- Tap **MANUAL INSPECTION** from home or results screen
- Check each physical observation. Suspicion Index updates live
- 16 checks across: Visual, Sound, Measurement, Light/Air/Magnetic

---

### AMPLIFY — Audio DSP Engine

**Setup**
1. Tap **AMPLIFY** tab
2. Microphone permission is requested automatically

**EQ + Presets**
- Select a preset row: **Low Voice, High Voice, Music, Broadcast, De-Ess, Flat**
- Presets configure: High-pass cutoff, EQ band gains (lowShelf/lowMid/mid/hiMid), presence boost, dynamic compressor ratio

**Source Mode**
- **HUMAN** — narrow band 200–3500Hz, +6dB presence, fast gate. Use for voice isolation
- **MEDIA** — wide band 80Hz–12kHz, flat EQ, light compression. Use for TV/radio clarity

**Noise Suppression**
- Tap **NOISE SUPPRESS** while the room is quiet — captures noise floor spectrum
- Activates spectral subtraction against learned profile
- **CALIBRATE** button resets the P25 noise gate threshold

**Source Classification**
- Auto-runs every 8 frames
- Displays: **HUMAN VOICE / MEDIA / AMBIENT / SILENCE** + confidence %
- Uses spectral flux, AM modulation rate, sibilance variance, formant transitions

**Mechanical Detection**
- Detects **FAN / AC / HVAC** in background using harmonic scoring at 20/60/120Hz bands
- Alert appears in header when score exceeds threshold

**Closed Captions**
- Tap **CC** to start continuous Web Speech API transcription
- Transcript scrolls in real-time below controls
- Language defaults to en-US

**Mute Gates**
- **🔊 HUMAN** — mutes human voice band (200–3500Hz). Tap to toggle

**Record**
- Tap **⏺ RECORD** to capture raw audio stream as WebM
- Tap **⏹ STOP** — file downloads automatically

**Gain**
- Slider: 0× to 4×. Applied post-gate, pre-output

---

### NIGHT VISION — NVG Camera

**Setup**
1. Tap **NIGHT VISION** tab
2. Camera permission is requested automatically — rear camera by default

**Palettes**
| Mode | Description |
|---|---|
| **NVG** | Classic night vision green. Boosted luminance ×1.3 |
| **THERMAL** | False-color thermal: purple→red→orange→white |
| **RAINBOW** | Full spectrum mapping: blue→cyan→green→yellow |
| **FUSION** | Purple→magenta→orange. High-contrast scenes |
| **PHOSPHOR** | Soft green phosphor CRT look |
| **AMBER** | Amber/gold tone. Reduces eye strain |

**Processing pipeline** (runs every frame)
1. Temporal blend noise reduction (α=0.72) — smooths grain
2. CLAHE 6×6 tile grid (clip=3.5) — local contrast enhancement
3. Brightness adjustment (−1 to +1)
4. Motion detection (frame diff, adjustable sensitivity)
5. Sobel edge overlay (optional)
6. LUT palette application
7. Motion blob labeling + threat boxes

**Toggles**
| Toggle | Function |
|---|---|
| **⊕ RETICLE** | Center crosshair |
| **⬥ MOTION** | Motion detection + blob target boxes |
| **◈ EDGES** | Sobel edge overlay blended onto output |
| **◎ DENOISE** | Temporal blend noise reduction |
| **↺ FLIP** | Switch front/rear camera |

**Sliders**
- **BRIGHTNESS** — −1 (darken) to +1 (brighten), applied post-CLAHE
- **SENSITIVITY** — motion detection threshold. Higher = more sensitive
- **ZOOM** — 1×–10× (hardware zoom where available, CSS scale fallback)

**HUD elements**
- Corner brackets (color matches palette)
- Reticle crosshair + center dot
- Target boxes on motion blobs: `TGT-A HIGH`, `TGT-B MED`, etc.
- Compass heading + cardinal direction (requires device orientation permission)
- FPS counter + palette + motion status bar

**Recording**
- **⏺ REC** — captures processed canvas output as WebM/VP9 (not raw camera)
- **📷 SNAP** — saves PNG screenshot of current processed frame

---

### DUAL CAM — Dual Camera Studio

Standalone at `/dualcam.html`, also mounted as the fourth VIGIL tab. Zero dependencies, one canvas compositor, everything on-device.

**Setup**
1. Tap **DUAL CAM** — grant camera (and microphone, if you record with audio)
2. Rear camera becomes **CAM A**, front camera becomes **CAM B**
3. If the device can only serve one stream at a time, DUALCAM drops to SOLO automatically and says so

**Composition**
| Layout | Behaviour |
|---|---|
| **SPLIT** | Two tiles. AUTO axis = side-by-side in landscape, stacked in portrait. Seam ratio 15–85% |
| **PIP** | One full feed with the other inset. Drag the inset anywhere, or snap to a corner. Size 15–60%, shape rect / rounded / circle |
| **BLEND** | Both feeds in one frame — screen, multiply, difference, lighten, overlay — with an opacity mix |
| **SOLO A / SOLO B** | One feed full-frame. Double-tap any tile to isolate, double-tap again to return |

Output aspect locks to SCREEN, 16:9, 4:3, 1:1 or 9:16 — stills and video inherit it. `SWAP A ↔ B` exchanges which feed is primary without touching either camera's settings.

**Per-camera image chain** — every control below is independent per feed
- **Looks** — NONE, NVG, THERMAL, RAINBOW, FUSION, AMBER, PHOSPHOR, MONO, SEPIA, ICE, INVERT
- **Adjustments** — brightness, contrast, saturation, gamma, sharpen (unsharp mask)
- **EDGES** — Sobel overlay · **DENOISE** — temporal blend · **FREEZE** — hold the frame (still records, still captures)
- **Geometry** — mirror (front cameras start mirrored), rotation 0/90/180/270
- **Zoom** — 1×–12×, hardware zoom where the track exposes it, digital crop otherwise. Pinch a tile to zoom only that feed
- **Hardware** — exposure compensation, focus mode and white balance appear only when the camera reports the capability. Tap a tile for point focus
- **LINK A+B** mirrors adjustments across both feeds; **COPY A → B** clones one camera's look onto the other

**Detection**
- Independent frame-difference detector per camera on a 96×72 grid
- Sensitivity sets the difference threshold, trigger area sets the minimum blob size
- Blobs labelled `TGT-A…TGT-F`, ranked CRIT → TRK by area
- **AUTO-CAP** saves a full-resolution still from the camera that fired, with a per-camera cooldown
- Overlays: reticle, corner brackets, luma histogram, roll level, compass strip, grid (thirds / 4×4 / golden / cross)

**Capture**
| Control | Behaviour |
|---|---|
| Shutter | Writes the composite exactly as framed |
| ALSO SAVE A+B | Adds a full-resolution frame per camera alongside the composite |
| Format | JPEG / PNG / WEBP with a quality slider |
| Self-timer | 3 / 5 / 10 s with an on-screen count |
| Burst | ×3 / ×5 / ×10 at a chosen interval |
| Video — COMPOSITE | One file of the composited frame, 2.5–24 Mbps, optional mic audio |
| Video — SEPARATE | Two files at once, one per camera, each at its own native resolution with its processing applied |
| Pause | The timer button pauses and resumes a recording without splitting the file |
| Stamps | Live timestamp, GPS coordinates and a custom watermark burned into stills and every video frame |

**Output** — gallery with download, system share sheet and delete. `KEEP GALLERY` mirrors captures into IndexedDB so they survive a reload; `AUTO-DOWNLOAD` writes each capture straight to disk.

**Keys** — `Space` shutter · `R` record · `P` pause · `1–5` split/pip/blend/solo A/solo B · `S` swap · `G` grid · `T` torch · `M` motion · `C` controls · `F` fullscreen · `H` help · `Esc` close


## Architecture

```
vigil/
├── index.html                  ← Shell, tab router, obsidian/gold, health dot
├── manifest.json               ← PWA
├── sw.js                       ← Service worker (vigil-v3)
├── vercel.json                 ← COOP/COEP headers, camera/mic Permissions-Policy
├── dualcam.html                ← DUAL CAM — standalone dual camera studio (no dependencies)
└── modules/
    ├── liminal/engine.js       ← Full LIMINAL detection engine (2100+ lines)
    ├── amplify/engine.js       ← Full AMPLIFY DSP engine (700+ lines)
    └── nightvision/engine.js  ← Full NVS camera engine (500+ lines)
```

**Module contract** — every engine exports `{ init(container), destroy(), health() }`.
Shell lazy-loads on tab activation. Calls `destroy()` + releases MediaStreams on tab leave.
No module holds global state. RAF arbitration prevents competing render loops.
Telemetry polls `health()` every 5s → drives header status dot (green/amber/red).

---

## Deploy

```bash
# Vercel — connect cloudygetty-ai/vigil, framework: Other, root: /
# No build command. No install. Output directory: .
vercel deploy --prod
```

Headers set in `vercel.json`:
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Embedder-Policy: require-corp`
- `Permissions-Policy: camera=*, microphone=*`

These are required for AudioWorklet, SharedArrayBuffer, and camera access on all browsers.

---

## Design System

| Token | Value |
|---|---|
| Background | `#0D0A14` obsidian |
| Surface | `#13101E` |
| Accent | `#C9A84C` gold |
| Display font | Cinzel 700 |
| UI font | DM Mono 400 |
| Health nominal | `#3DBA7A` |
| Health degraded | `#F5A623` |
| Health fault | `#E53E3E` |

---

## Roadmap

| Priority | Item |
|---|---|
| `P1` | Vercel deploy (connect repo at vercel.com/new) |
| `P1` | Wire Anthropic API key for Claude AI vision in LIMINAL |
| `P2` | Compass HUD in NVS — request orientation permission on first tap |
| `P2` | Full Hough + GLCM + magnetometer pipeline wired end-to-end in LIMINAL |
| `P3` | Swipe gesture tab navigation |
| `P3` | PWA icon set (assets/icon-512.png) |
| `P3` | Wire SUSURRUS into the shell tab bar |

---

`cloudygetty-ai/vigil` · Sentinel Engine v6.0 · ENTROPY-ZERO
