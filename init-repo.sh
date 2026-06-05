#!/bin/bash
# Run from inside the vigil/ directory
set -e

echo "→ Initializing VIGIL repo"
git init
git remote add origin https://github.com/cloudygetty-ai/vigil.git

echo "→ Staging all files"
git add .
git commit -m "feat: VIGIL v1.0 — LIMINAL + AMPLIFY + NIGHT VISION unified PWA

- Shell: tab router, obsidian/gold aesthetic, Cinzel/DM Mono
- Shared: MediaStream arbitration, RAF arbitration, Telemetry (5s health loop)
- Liminal: Sobel edge detection overlay, scan mode, camera+mic acquire
- Amplify: AudioWorklet noise gate (Blob URL), P25 calibration, waveform canvas
- Night Vision: 6 LUT palettes, motion detection, MediaRecorder capture
- PWA: manifest.json + sw.js (vigil-v1 cache)
- Vercel: COOP/COEP headers, camera/mic Permissions-Policy
- TODO[P1]: full Hough+GLCM+magnetometer+FFT pipeline in Liminal
- TODO[P2]: Claude AI vision integration in Liminal"

echo "→ Pushing to cloudygetty-ai/vigil"
git branch -M main
git push -u origin main

echo "✓ VIGIL pushed"
