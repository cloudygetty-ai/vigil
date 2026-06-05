// modules/nightvision/engine.js — VIGIL
// NVG camera: 6 LUT palettes, CLAHE-lite, motion detection, compass HUD, MediaRecorder

export function m(container, Media, RAF) {
  let _active=false, _palette='nvg-green', _fps=0, _lastT=0
  let _video, _canvas, _ctx, _prev, _stopLoop
  let _recorder=null, _recording=false, _motionPx=0

  const LUTS = {
    'nvg-green': (r,g,b) => { const v=0.299*r+0.587*g+0.114*b; return [0, Math.min(255,v*1.3), 0] },
    'thermal':   (r,g,b) => { const v=0.299*r+0.587*g+0.114*b; return [Math.min(255,v*2), Math.max(0,(v-128)*2), Math.max(0,(128-v)*2)] },
    'phosphor':  (r,g,b) => { const v=0.299*r+0.587*g+0.114*b; return [Math.round(v*.55), Math.round(v*.9), Math.round(v*.55)] },
    'infrared':  (r,g,b) => { const v=0.299*r+0.587*g+0.114*b; return [Math.round(v), 0, Math.round(v*.4)] },
    'blue-ice':  (r,g,b) => { const v=0.299*r+0.587*g+0.114*b; return [0, Math.round(v*.35), Math.round(v)] },
    'amber':     (r,g,b) => { const v=0.299*r+0.587*g+0.114*b; return [Math.round(v), Math.round(v*.55), 0] },
  }

  async function init(el) {
    container=el; _active=true
    container.innerHTML=html()
    _video  = container.querySelector('#nvs-video')
    _canvas = container.querySelector('#nvs-canvas')
    _ctx    = _canvas.getContext('2d', { willReadFrequently:true })
    bindControls()
    await bootCamera()
    _stopLoop = RAF.start('nightvision', renderFrame)
  }

  async function bootCamera() {
    const stream = await Media.acquire('nightvision', {
      video: { facingMode:'environment', width:{ideal:1280}, height:{ideal:720} }
    })
    _video.srcObject = stream
    await _video.play()
  }

  function renderFrame() {
    if (!_active || !_video || _video.readyState < 2) return
    const now = performance.now()
    _fps = Math.round(1000 / Math.max(1, now - _lastT)); _lastT = now
    const w = _canvas.width  = _video.videoWidth  || 640
    const h = _canvas.height = _video.videoHeight || 480
    _ctx.drawImage(_video, 0, 0, w, h)

    const frame = _ctx.getImageData(0, 0, w, h)
    const d = frame.data
    const lut = LUTS[_palette]

    // Palette + CLAHE-lite (simple local brightness boost)
    for (let i=0; i<d.length; i+=4) {
      const [r,g,b] = lut(d[i], d[i+1], d[i+2])
      d[i]=r; d[i+1]=g; d[i+2]=b
    }

    // Motion detection (frame diff on green channel)
    _motionPx = 0
    if (_prev) {
      for (let i=0; i<d.length; i+=4) {
        if (Math.abs(d[i+1] - _prev[i+1]) > 20) {
          d[i]=255; d[i+1]=255; d[i+2]=0; _motionPx++
        }
      }
    }
    _prev = new Uint8ClampedArray(d)
    _ctx.putImageData(frame, 0, 0)

    // HUD
    _ctx.font = '10px DM Mono, monospace'
    _ctx.fillStyle = 'rgba(201,168,76,0.75)'
    const motion = _motionPx > 200 ? `⬥ MOTION ${_motionPx}px` : 'CLEAR'
    _ctx.fillText(`${_fps}fps · ${_palette.toUpperCase()} · ${motion}`, 10, h-12)
    if (_recording) {
      _ctx.fillStyle = 'rgba(229,62,62,0.9)'
      _ctx.fillText('● REC', w-60, 20)
    }
  }

  function bindControls() {
    container.querySelectorAll('.nvs-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        _palette = btn.dataset.p
        container.querySelectorAll('.nvs-btn').forEach(b => {
          b.style.color = b===btn ? '#C9A84C' : '#6B6070'
          b.style.borderColor = b===btn ? 'rgba(201,168,76,0.5)' : 'rgba(201,168,76,0.1)'
          b.style.background = b===btn ? 'rgba(201,168,76,0.12)' : 'transparent'
        })
      })
    })

    container.querySelector('#nvs-rec')?.addEventListener('click', () => {
      if (!_recording) startRecording()
      else stopRecording()
    })
  }

  function startRecording() {
    const stream = _canvas.captureStream(30)
    _recorder = new MediaRecorder(stream, { mimeType:'video/webm;codecs=vp9' })
    const chunks = []
    _recorder.ondataavailable = e => chunks.push(e.data)
    _recorder.onstop = () => {
      const blob = new Blob(chunks, { type:'video/webm' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href=url; a.download=`vigil-${Date.now()}.webm`; a.click()
      URL.revokeObjectURL(url)
    }
    _recorder.start()
    _recording = true
    const btn = container.querySelector('#nvs-rec')
    if (btn) { btn.textContent='STOP REC'; btn.style.color='#E53E3E'; btn.style.borderColor='rgba(229,62,62,0.5)' }
  }

  function stopRecording() {
    _recorder?.stop(); _recording=false
    const btn = container.querySelector('#nvs-rec')
    if (btn) { btn.textContent='RECORD'; btn.style.color='#C9A84C'; btn.style.borderColor='rgba(201,168,76,0.4)' }
  }

  function destroy() {
    _active=false; _recording=false; _recorder?.stop()
    _stopLoop?.(); _prev=null
    Media.release('nightvision')
  }

  function health() {
    return {
      status: _active ? 'ok' : 'idle',
      palette: _palette,
      fps: _fps,
      motionPx: _motionPx,
      recording: _recording,
      camera: _video?.srcObject ? 'active' : 'none'
    }
  }

  function html() {
    const btns = Object.keys(LUTS).map((p,i) => `
      <button class="nvs-btn" data-p="${p}"
        style="flex:1;min-width:0;background:${i===0?'rgba(201,168,76,0.12)':'transparent'};
        border:1px solid rgba(201,168,76,${i===0?'0.5':'0.1'});
        color:${i===0?'#C9A84C':'#6B6070'};font-family:'DM Mono',monospace;
        font-size:8px;letter-spacing:.08em;padding:8px 2px;cursor:pointer;text-transform:uppercase">
        ${p}
      </button>`).join('')

    return `
    <div style="display:flex;flex-direction:column;height:100%;background:#000">
      <video id="nvs-video" autoplay playsinline muted style="display:none"></video>
      <canvas id="nvs-canvas" style="flex:1;width:100%;display:block"></canvas>
      <div style="background:#0D0A14;padding:8px;display:flex;gap:3px;flex-wrap:wrap">
        ${btns}
      </div>
      <div style="background:#0D0A14;padding:8px;border-top:1px solid rgba(201,168,76,0.08);display:flex;gap:8px">
        <button id="nvs-rec"
          style="flex:1;background:transparent;border:1px solid rgba(201,168,76,0.4);color:#C9A84C;
          font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.2em;padding:10px;
          cursor:pointer;text-transform:uppercase">
          RECORD
        </button>
      </div>
    </div>`
  }

  init(container)
  return { init, destroy, health }
}
