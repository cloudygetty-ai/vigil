// modules/amplify/engine.js — VIGIL
// Audio DSP: AudioWorklet noise gate, hysteresis, P25 calibration, waveform canvas

export function m(container, Media) {
  let _active=false, _ctx=null, _worklet=null, _gain=null
  let _pressure={ rms:0, peak:0, gated:true }
  const RING = new Array(120).fill(0); let _head=0

  const WORKLET_SRC = `
class NoiseGateProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._thr=0.02; this._hyst=0.005; this._open=false
    this._ring=new Float32Array(300); this._rhead=0
    this._calibrated=false; this._cframes=0
    this.port.onmessage=e=>{
      if(e.data.type==='setThreshold') this._thr=e.data.value
      if(e.data.type==='calibrate'){this._calibrated=false;this._cframes=0}
    }
  }
  process(inputs,outputs){
    const inp=inputs[0]?.[0]; const out=outputs[0]?.[0]
    if(!inp||!out) return true
    let rms=0
    for(let i=0;i<inp.length;i++) rms+=inp[i]*inp[i]
    rms=Math.sqrt(rms/inp.length)
    this._ring[this._rhead++%300]=rms
    if(!this._calibrated&&this._cframes++>150){
      const s=[...this._ring].sort((a,b)=>a-b)
      this._thr=s[Math.floor(s.length*0.25)]*1.5
      this._calibrated=true
    }
    this._open=this._open ? rms>this._thr-this._hyst : rms>this._thr+this._hyst
    const g=this._open?1:0.01
    for(let i=0;i<inp.length;i++) out[i]=inp[i]*g
    const peak=inp.reduce((m,v)=>Math.max(m,Math.abs(v)),0)
    this.port.postMessage({rms,peak,gated:!this._open})
    return true
  }
}
registerProcessor('vigil-gate',NoiseGateProcessor)
`

  async function init(el) {
    container=el; _active=true
    container.innerHTML=html()
    bindControls()
    await bootDSP()
    drawLoop()
  }

  async function bootDSP() {
    try {
      const stream = await Media.acquire('amplify', {
        audio: { echoCancellation:false, noiseSuppression:false, autoGainControl:false }
      })
      _ctx = new AudioContext({ sampleRate:48000 })
      const blob = new Blob([WORKLET_SRC], { type:'application/javascript' })
      const url  = URL.createObjectURL(blob)
      await _ctx.audioWorklet.addModule(url)
      URL.revokeObjectURL(url)
      const src = _ctx.createMediaStreamSource(stream)
      _worklet   = new AudioWorkletNode(_ctx, 'vigil-gate')
      _gain      = _ctx.createGain(); _gain.gain.value=1
      src.connect(_worklet).connect(_gain).connect(_ctx.destination)
      _worklet.port.onmessage = e => {
        _pressure = e.data
        RING[_head++ % 120] = e.data.rms
        updateMeter(e.data)
      }
    } catch(e) { throw e }
  }

  function updateMeter(data) {
    const bar = container.querySelector('#amp-meter')
    if (!bar) return
    const pct = Math.min(100, data.rms * 800)
    bar.style.width = pct + '%'
    bar.style.background = data.gated ? '#3a3040' : '#C9A84C'
  }

  function drawLoop() {
    const canvas = container.querySelector('#amp-canvas')
    if (!canvas || !_active) return
    const ctx = canvas.getContext('2d')
    const w=canvas.width, h=canvas.height
    ctx.clearRect(0,0,w,h)
    ctx.strokeStyle = _pressure.gated ? 'rgba(201,168,76,0.25)' : '#C9A84C'
    ctx.lineWidth = 1.5; ctx.beginPath()
    const step = w/120
    for (let i=0;i<120;i++) {
      const val = RING[(_head+i)%120]
      const x=i*step, y=h/2 - val*h*10
      i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y)
    }
    ctx.stroke()
    if (_active) requestAnimationFrame(drawLoop)
  }

  function bindControls() {
    container.querySelector('#amp-gain')?.addEventListener('input', e => {
      if (_gain) _gain.gain.value = parseFloat(e.target.value)
    })
    container.querySelector('#amp-cal')?.addEventListener('click', () => {
      _worklet?.port.postMessage({ type:'calibrate' })
    })
  }

  function destroy() {
    _active=false
    _worklet?.disconnect(); _gain?.disconnect(); _ctx?.close()
    Media.release('amplify')
  }

  function health() {
    return {
      status: _active && _ctx?.state==='running' ? 'ok' : _active ? 'degraded' : 'idle',
      audioContext: _ctx?.state ?? 'none',
      rms: +(_pressure.rms?.toFixed(4)??0),
      peak: +(_pressure.peak?.toFixed(4)??0),
      gated: _pressure.gated,
      sampleRate: _ctx?.sampleRate ?? 0
    }
  }

  function html() { return `
    <div style="display:flex;flex-direction:column;height:100%;background:#0D0A14;padding:20px;gap:16px;overflow-y:auto">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <span style="font-family:'Cinzel',serif;font-size:13px;letter-spacing:.3em;color:#C9A84C;text-transform:uppercase">
          Audio Engine
        </span>
        <span style="font-size:9px;letter-spacing:.15em;color:#6B6070">48kHz · Noise Gate</span>
      </div>

      <canvas id="amp-canvas" width="600" height="100"
        style="width:100%;background:#0A0812;border:1px solid rgba(201,168,76,0.1)"></canvas>

      <div style="background:#0A0812;border:1px solid rgba(201,168,76,0.1);padding:12px;display:flex;flex-direction:column;gap:8px">
        <span style="font-size:9px;letter-spacing:.2em;color:#6B6070;text-transform:uppercase">Signal Level</span>
        <div style="background:#0D0A14;height:6px;border-radius:1px;overflow:hidden">
          <div id="amp-meter" style="height:100%;width:0%;background:#C9A84C;transition:width 0.05s"></div>
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:12px">
        <span style="font-size:9px;letter-spacing:.15em;color:#6B6070;text-transform:uppercase;white-space:nowrap">GAIN</span>
        <input id="amp-gain" type="range" min="0" max="4" step="0.05" value="1"
          style="flex:1;accent-color:#C9A84C;cursor:pointer">
        <span style="font-size:9px;color:#C9A84C;width:28px;text-align:right">1.0×</span>
      </div>

      <button id="amp-cal"
        style="background:transparent;border:1px solid rgba(201,168,76,0.25);color:#C9A84C;
        font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.2em;padding:12px;
        cursor:pointer;text-transform:uppercase;transition:border-color 0.2s">
        CALIBRATE NOISE FLOOR
      </button>

      <div style="margin-top:auto;padding-top:8px;border-top:1px solid rgba(201,168,76,0.08)">
        <div style="font-size:9px;color:#6B6070;letter-spacing:.1em;line-height:1.8">
          P25 auto-calibration · Hysteresis gate · 300-slot ring buffer
        </div>
      </div>
    </div>` }

  init(container)
  return { init, destroy, health }
}
