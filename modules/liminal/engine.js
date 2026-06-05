// modules/liminal/engine.js — VIGIL
// Hidden door detection: Sobel, Hough, GLCM, magnetometer, acoustic FFT

export function m(container, Media, RAF) {
  let _active = false, _scanning = false, _scanCount = 0
  let _video, _canvas, _ctx, _stopLoop
  const state = { status: 'idle', detections: [], lastScanMs: null }

  async function init(el) {
    container = el; _active = true
    container.innerHTML = html()
    _video  = container.querySelector('#lim-video')
    _canvas = container.querySelector('#lim-canvas')
    _ctx    = _canvas.getContext('2d', { willReadFrequently: true })
    bindControls()
    await bootCamera()
    _stopLoop = RAF.start('liminal', renderFrame)
    state.status = 'ready'
  }

  async function bootCamera() {
    try {
      const stream = await Media.acquire('liminal', {
        video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: true
      })
      _video.srcObject = stream
      await _video.play()
    } catch(e) { state.status = 'fault'; throw e }
  }

  function renderFrame() {
    if (!_active || !_video || _video.readyState < 2) return
    const w = _canvas.width  = _video.videoWidth  || 640
    const h = _canvas.height = _video.videoHeight || 480
    _ctx.drawImage(_video, 0, 0, w, h)
    if (_scanning) sobelOverlay(w, h)
    drawHUD(w, h)
  }

  function sobelOverlay(w, h) {
    const frame = _ctx.getImageData(0, 0, w, h)
    const d = frame.data
    const out = new Uint8ClampedArray(d.length)
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const g = (ox, oy) => { const j = ((y+oy)*w+(x+ox))*4; return 0.299*d[j]+0.587*d[j+1]+0.114*d[j+2] }
        const gx = -g(-1,-1)+g(1,-1)-2*g(-1,0)+2*g(1,0)-g(-1,1)+g(1,1)
        const gy = -g(-1,-1)-2*g(0,-1)-g(1,-1)+g(-1,1)+2*g(0,1)+g(1,1)
        const mag = Math.min(255, Math.sqrt(gx*gx + gy*gy))
        const i = (y*w+x)*4
        if (mag > 80) { out[i]=201; out[i+1]=168; out[i+2]=76; out[i+3]=mag }
        else { out[i+3]=0 }
      }
    }
    _ctx.putImageData(new ImageData(out, w, h), 0, 0)
  }

  function drawHUD(w, h) {
    _ctx.font = '10px DM Mono, monospace'
    _ctx.fillStyle = 'rgba(201,168,76,0.7)'
    _ctx.fillText(`VIGIL · LIMINAL · ${_scanning?'SCANNING':'STANDBY'} · ${_scanCount} SCANS`, 10, h-12)
  }

  function bindControls() {
    container.querySelector('#lim-scan-btn')?.addEventListener('click', () => {
      _scanning = !_scanning
      if (_scanning) { _scanCount++; state.lastScanMs = Date.now() }
      const btn = container.querySelector('#lim-scan-btn')
      btn.textContent = _scanning ? 'ABORT SCAN' : 'INITIATE SCAN'
      btn.style.borderColor = _scanning ? 'rgba(201,168,76,0.9)' : 'rgba(201,168,76,0.4)'
      btn.style.boxShadow = _scanning ? '0 0 16px rgba(201,168,76,0.2)' : 'none'
      // TODO[P1]: full Hough + GLCM + magnetometer + FFT pipeline
      // TODO[P2]: Claude AI vision frame analysis
    })
  }

  function destroy() { _active=false; _scanning=false; _stopLoop?.(); state.status='idle' }

  function health() {
    return {
      status: _active ? (_scanning?'ok':'ready') : 'idle',
      scans: _scanCount,
      lastScan: state.lastScanMs ? `${((Date.now()-state.lastScanMs)/1000).toFixed(1)}s ago` : 'none',
      detections: state.detections.length,
      camera: _video?.srcObject ? 'active' : 'none'
    }
  }

  function html() { return `
    <div style="position:relative;width:100%;height:100%;background:#000">
      <video id="lim-video" autoplay playsinline muted
        style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"></video>
      <canvas id="lim-canvas" style="position:absolute;inset:0;width:100%;height:100%"></canvas>
      <div style="position:absolute;top:16px;left:16px;right:16px;display:flex;justify-content:space-between">
        <div style="background:rgba(13,10,20,0.8);border:1px solid rgba(201,168,76,0.2);padding:6px 12px">
          <span style="font-family:'Cinzel',serif;font-size:10px;letter-spacing:.3em;color:#C9A84C">EDGE DETECT</span>
        </div>
        <div style="background:rgba(13,10,20,0.8);border:1px solid rgba(61,186,122,0.3);padding:6px 12px;
          font-size:9px;letter-spacing:.2em;color:#3DBA7A">STANDBY</div>
      </div>
      <div style="position:absolute;bottom:24px;left:0;right:0;display:flex;justify-content:center;padding:0 20px">
        <button id="lim-scan-btn"
          style="flex:1;max-width:260px;background:rgba(13,10,20,0.85);border:1px solid rgba(201,168,76,0.4);
          color:#C9A84C;font-family:'Cinzel',serif;letter-spacing:.2em;font-size:11px;
          padding:14px;cursor:pointer;text-transform:uppercase;transition:all 0.2s">
          INITIATE SCAN
        </button>
      </div>
    </div>` }

  init(container)
  return { init, destroy, health }
}
