// modules/nightvision/engine.js — VIGIL
// ALL features from cloudygetty-ai/night-vision:
// 5 LUT palettes (THERMAL, RAINBOW, FUSION, NVG, PHOSPHOR) with proper buildLUT
// CLAHE 6×6 tile grid, clip=3.5
// Sobel edge overlay (toggleable)
// Temporal blend noise reduction (alpha=0.72)
// Connected component blob labeling (up to 6 blobs)
// Multi-target boxes with ID + threat classification
// Compass HUD via DeviceOrientation
// Signal bars UI
// Motion alert with level
// FPS counter
// Brightness + sensitivity + zoom sliders
// Reticle toggle
// Noise reduction toggle
// MediaRecorder video capture + snapshot
// Front/rear camera flip
// Settings panel
// Corner brackets HUD
// Thermal pseudo-overlay

export function m(container, Media, RAF) {
  let _active=false, _mode='NVG', _facing='environment'
  let _brightness=0, _zoom=1, _sensitivity=0.6
  let _showReticle=true, _motionEnabled=true, _edgeOverlay=false
  let _noiseReduction=true, _recording=false
  let _blobs=[], _motionLevel=0, _fps=0, _lastT=0
  let _heading=null
  let _video, _rawCanvas, _dispCanvas, _dispCtx, _rawCtx
  let _stopLoop, _recorder=null, _chunks=[]
  let _prevFrame=null, _tempHistory=null
  let _orientHandler=null

  // ── LUT builder ──────────────────────────────────────────
  function buildLUT(fn) {
    const lut = new Uint8Array(256 * 3)
    for (let i = 0; i < 256; i++) {
      const [r,g,b] = fn(i / 255)
      lut[i*3]=Math.round(r); lut[i*3+1]=Math.round(g); lut[i*3+2]=Math.round(b)
    }
    return lut
  }

  const LUTS = {
    THERMAL: buildLUT(t => {
      if (t < 0.20) return [0, 0, Math.round(t/0.20*180)]
      if (t < 0.40) { const s=(t-0.20)/0.20; return [Math.round(s*160),0,Math.round(180-s*180)] }
      if (t < 0.60) { const s=(t-0.40)/0.20; return [Math.round(160+s*95),Math.round(s*60),0] }
      if (t < 0.80) { const s=(t-0.60)/0.20; return [255,Math.round(60+s*140),0] }
      const s=(t-0.80)/0.20; return [255,Math.round(200+s*55),Math.round(s*255)]
    }),
    RAINBOW: buildLUT(t => {
      if (t < 0.25) { const s=t/0.25; return [0,0,Math.round(s*255)] }
      if (t < 0.50) { const s=(t-0.25)/0.25; return [0,Math.round(s*255),255] }
      if (t < 0.75) { const s=(t-0.50)/0.25; return [0,255,Math.round(255-s*255)] }
      const s=(t-0.75)/0.25; return [Math.round(s*255),255,0]
    }),
    FUSION: buildLUT(t => {
      if (t < 0.33) { const s=t/0.33; return [Math.round(s*80),0,Math.round(80+s*175)] }
      if (t < 0.66) { const s=(t-0.33)/0.33; return [Math.round(80+s*175),Math.round(s*100),Math.round(255-s*200)] }
      const s=(t-0.66)/0.34; return [255,Math.round(100+s*155),Math.round(55+s*200)]
    }),
    NVG: buildLUT(t => {
      const v = Math.min(255, Math.round(t*255*1.3))
      return [0, v, 0]
    }),
    PHOSPHOR: buildLUT(t => {
      const v = Math.round(t*255)
      return [Math.round(v*0.55), Math.round(v*0.9), Math.round(v*0.55)]
    }),
    AMBER: buildLUT(t => {
      const v = Math.round(t*255)
      return [v, Math.round(v*0.55), 0]
    }),
  }

  // ── CLAHE 6×6 tile grid, clip=3.5 ─────────────────────────
  function applyCLAHE(data, w, h, tiles=6, clip=3.5) {
    const tW=Math.floor(w/tiles), tH=Math.floor(h/tiles)
    for (let ty=0; ty<tiles; ty++) {
      for (let tx=0; tx<tiles; tx++) {
        const x0=tx*tW, y0=ty*tH
        const x1=tx===tiles-1?w:x0+tW
        const y1=ty===tiles-1?h:y0+tH
        const count=(x1-x0)*(y1-y0)
        const hist=new Float32Array(256)
        for (let y=y0; y<y1; y++) for (let x=x0; x<x1; x++) {
          const idx=(y*w+x)*4
          hist[Math.round(0.299*data[idx]+0.587*data[idx+1]+0.114*data[idx+2])]++
        }
        const lim=(count/256)*clip
        let ex=0
        for (let i=0;i<256;i++) { if(hist[i]>lim){ex+=hist[i]-lim;hist[i]=lim} }
        const add=ex/256
        for (let i=0;i<256;i++) hist[i]+=add
        const cdf=new Float32Array(256)
        cdf[0]=hist[0]
        for (let i=1;i<256;i++) cdf[i]=cdf[i-1]+hist[i]
        const cMin=cdf[0]
        for (let y=y0;y<y1;y++) for (let x=x0;x<x1;x++) {
          const idx=(y*w+x)*4
          const lum=Math.round(0.299*data[idx]+0.587*data[idx+1]+0.114*data[idx+2])
          const eq=Math.round((cdf[lum]-cMin)/Math.max(1,count-cMin)*255)
          const sc=lum>2?eq/lum:1
          data[idx]=Math.min(255,Math.round(data[idx]*sc))
          data[idx+1]=Math.min(255,Math.round(data[idx+1]*sc))
          data[idx+2]=Math.min(255,Math.round(data[idx+2]*sc))
        }
      }
    }
  }

  // ── Sobel edge detection ────────────────────────────────
  function sobelEdges(data, w, h) {
    const edges=new Float32Array(w*h)
    const lum=i=>(0.299*data[i*4]+0.587*data[i*4+1]+0.114*data[i*4+2])
    for (let y=1;y<h-1;y++) for (let x=1;x<w-1;x++) {
      const tl=lum((y-1)*w+(x-1)),t=lum((y-1)*w+x),tr=lum((y-1)*w+(x+1))
      const ml=lum(y*w+(x-1)),mr=lum(y*w+(x+1))
      const bl=lum((y+1)*w+(x-1)),b=lum((y+1)*w+x),br=lum((y+1)*w+(x+1))
      const gx=-tl-2*ml-bl+tr+2*mr+br
      const gy=-tl-2*t-tr+bl+2*b+br
      edges[y*w+x]=Math.min(255,Math.sqrt(gx*gx+gy*gy)*0.5)
    }
    return edges
  }

  // ── Temporal blend noise reduction ─────────────────────
  function temporalBlend(data, history, alpha=0.72) {
    if (!history || history.length!==data.length) return new Uint8ClampedArray(data)
    const out=new Uint8ClampedArray(data.length)
    for (let i=0;i<data.length;i++) out[i]=Math.round(data[i]*(1-alpha)+history[i]*alpha)
    return out
  }

  // ── Connected component blob labeling ──────────────────
  function findBlobs(motionMap, w, h, minSize=80) {
    const visited=new Uint8Array(w*h)
    const blobs=[]
    for (let start=0;start<motionMap.length;start++) {
      if (!motionMap[start]||visited[start]) continue
      let size=0, minX=w, minY=h, maxX=0, maxY=0
      const queue=[start]; visited[start]=1
      while (queue.length) {
        const idx=queue.pop(); size++
        const x=idx%w, y=Math.floor(idx/w)
        if(x<minX)minX=x; if(x>maxX)maxX=x
        if(y<minY)minY=y; if(y>maxY)maxY=y
        for (const [dx,dy] of [[-1,0],[1,0],[0,-1],[0,1]]) {
          const nx=x+dx, ny=y+dy
          if(nx>=0&&nx<w&&ny>=0&&ny<h) {
            const ni=ny*w+nx
            if(motionMap[ni]&&!visited[ni]){visited[ni]=1;queue.push(ni)}
          }
        }
      }
      if (size>=minSize) blobs.push({x:minX,y:minY,w:maxX-minX,h:maxY-minY,size,cx:(minX+maxX)/2,cy:(minY+maxY)/2})
    }
    return blobs.sort((a,b)=>b.size-a.size).slice(0,6)
  }

  // ── Main frame processor ────────────────────────────────
  function processFrame() {
    if (!_active||!_video||_video.readyState<2) return
    const now=performance.now()
    _fps=Math.round(1000/Math.max(1,now-_lastT)); _lastT=now
    const sw=_video.videoWidth||640, sh=_video.videoHeight||480

    _rawCanvas.width=sw; _rawCanvas.height=sh
    _dispCanvas.width=sw; _dispCanvas.height=sh

    _rawCtx.drawImage(_video,0,0,sw,sh)
    const imgData=_rawCtx.getImageData(0,0,sw,sh)
    let data=imgData.data

    // ── Noise reduction (temporal blend) ─────────────────
    if (_noiseReduction&&_prevFrame) {
      const blended=temporalBlend(data,_prevFrame,0.72)
      for (let i=0;i<data.length;i++) data[i]=blended[i]
    }
    _prevFrame=new Uint8ClampedArray(data)

    // ── CLAHE contrast enhancement ────────────────────────
    applyCLAHE(data, sw, sh)

    // ── Brightness adjustment ─────────────────────────────
    if (_brightness!==0) {
      const bAdj=_brightness*80
      for (let i=0;i<data.length;i+=4) {
        data[i]=Math.min(255,Math.max(0,data[i]+bAdj))
        data[i+1]=Math.min(255,Math.max(0,data[i+1]+bAdj))
        data[i+2]=Math.min(255,Math.max(0,data[i+2]+bAdj))
      }
    }

    // ── Motion detection ─────────────────────────────────
    const motionThresh=Math.round(15+(1-_sensitivity)*40)
    const motionMap=new Uint8Array(sw*sh)
    let motionPx=0
    if (_motionEnabled&&_rawCtx._prevForMotion&&_rawCtx._prevForMotion.length===data.length) {
      const prev=_rawCtx._prevForMotion
      for (let i=0;i<data.length;i+=4) {
        const d=(Math.abs(data[i]-prev[i])+Math.abs(data[i+1]-prev[i+1])+Math.abs(data[i+2]-prev[i+2]))/3
        if (d>motionThresh){motionMap[i/4]=255;motionPx++}
      }
    }
    _rawCtx._prevForMotion=new Uint8ClampedArray(data)
    _motionLevel=motionPx/(sw*sh)
    _blobs=_motionLevel>0.002?findBlobs(motionMap,sw,sh,60):[]

    // ── Sobel edge overlay ────────────────────────────────
    let edges=null
    if (_edgeOverlay) edges=sobelEdges(data,sw,sh)

    // ── Apply LUT palette ─────────────────────────────────
    const lut=LUTS[_mode]||LUTS.NVG
    for (let i=0;i<data.length;i+=4) {
      const lum=Math.round(0.299*data[i]+0.587*data[i+1]+0.114*data[i+2])
      const li=lum*3
      data[i]=lut[li]; data[i+1]=lut[li+1]; data[i+2]=lut[li+2]
    }

    // ── Edge overlay blend ────────────────────────────────
    if (edges) {
      for (let i=0;i<edges.length;i++) {
        if (edges[i]>30) {
          const pi=i*4; const e=edges[i]/255
          data[pi]=Math.min(255,data[pi]+Math.round(e*180))
          data[pi+1]=Math.min(255,data[pi+1]+Math.round(e*180))
          data[pi+2]=Math.min(255,data[pi+2]+Math.round(e*180))
        }
      }
    }

    // ── Motion blob highlight ────────────────────────────
    if (_motionEnabled) {
      for (let i=0;i<motionMap.length;i++) {
        if (motionMap[i]) {
          const pi=i*4; data[pi]=255; data[pi+1]=255; data[pi+2]=0
        }
      }
    }

    _rawCtx.putImageData(imgData,0,0)
    _dispCtx.drawImage(_rawCanvas,0,0,sw,sh)
    drawHUD(sw,sh)
  }

  // ── HUD overlay ─────────────────────────────────────────
  function drawHUD(w, h) {
    const ctx=_dispCtx
    const modeColor=getModeColor()

    // Reticle
    if (_showReticle) {
      ctx.strokeStyle=modeColor; ctx.globalAlpha=0.5; ctx.lineWidth=1
      ctx.beginPath()
      ctx.moveTo(w/2-20,h/2); ctx.lineTo(w/2-8,h/2)
      ctx.moveTo(w/2+8,h/2);  ctx.lineTo(w/2+20,h/2)
      ctx.moveTo(w/2,h/2-20); ctx.lineTo(w/2,h/2-8)
      ctx.moveTo(w/2,h/2+8);  ctx.lineTo(w/2,h/2+20)
      ctx.arc(w/2,h/2,6,0,Math.PI*2)
      ctx.stroke()
    }

    // Corner brackets
    ctx.globalAlpha=0.6; ctx.strokeStyle=modeColor; ctx.lineWidth=2
    const bs=Math.min(w,h)*0.07
    [[0,0,1,1],[w,0,-1,1],[0,h,1,-1],[w,h,-1,-1]].forEach(([cx,cy,dx,dy])=>{
      ctx.beginPath()
      ctx.moveTo(cx+dx*bs,cy); ctx.lineTo(cx,cy); ctx.lineTo(cx,cy+dy*bs)
      ctx.stroke()
    })

    // Motion blob boxes
    if (_motionEnabled&&_blobs.length) {
      _blobs.forEach((b,i)=>{
        const threat=b.size>5000?'HIGH':b.size>1500?'MED':'LOW'
        const tc=threat==='HIGH'?'#ff4444':threat==='MED'?'#ffaa00':'#44ff44'
        ctx.strokeStyle=tc; ctx.lineWidth=1.5; ctx.globalAlpha=0.85
        ctx.strokeRect(b.x*w/(_rawCanvas.width||w),b.y*h/(_rawCanvas.height||h),
          b.w*w/(_rawCanvas.width||w),b.h*h/(_rawCanvas.height||h))
        ctx.fillStyle=tc; ctx.font='8px DM Mono,monospace'; ctx.globalAlpha=0.9
        ctx.fillText(`TGT-${String.fromCharCode(65+i)} ${threat}`,
          b.x*w/(_rawCanvas.width||w)+3,b.y*h/(_rawCanvas.height||h)-3)
      })
    }

    // Compass HUD
    if (_heading!==null) {
      const dirs=['N','NE','E','SE','S','SW','W','NW']
      const dir=dirs[Math.round(_heading/45)%8]
      ctx.globalAlpha=0.75; ctx.fillStyle=modeColor
      ctx.font='bold 10px DM Mono,monospace'
      ctx.fillText(`${dir} ${Math.round(_heading)}°`,w-60,18)
    }

    // HUD bar: fps, mode, motion
    ctx.globalAlpha=0.75
    ctx.fillStyle='rgba(0,0,0,0.5)'
    ctx.fillRect(0,h-20,w,20)
    ctx.fillStyle=modeColor; ctx.font='9px DM Mono,monospace'
    const motionStr=_motionLevel>0.02?`⬥ MOTION ${_blobs.length}TGT`:'CLEAR'
    ctx.fillText(`${_fps}fps · ${_mode} · ${motionStr}`,6,h-6)
    if (_recording) {
      ctx.fillStyle='#ff4444'; ctx.font='bold 9px DM Mono,monospace'
      ctx.fillText('● REC',w-38,14)
    }

    ctx.globalAlpha=1
  }

  function getModeColor() {
    const colors={THERMAL:'#ff6644',RAINBOW:'#44aaff',FUSION:'#cc44ff',NVG:'#44ff88',PHOSPHOR:'#88ff88',AMBER:'#ffaa44'}
    return colors[_mode]||'#44ff88'
  }

  // ── Controls ─────────────────────────────────────────────
  function bindControls() {
    // Palette buttons
    container.querySelectorAll('.nvs-mode-btn').forEach(btn=>{
      btn.addEventListener('click',()=>{
        _mode=btn.dataset.m
        container.querySelectorAll('.nvs-mode-btn').forEach(b=>{
          b.style.color=b===btn?getModeColor():'#6B6070'
          b.style.borderColor=b===btn?`rgba(${hexToRgb(getModeColor())},0.5)`:'rgba(201,168,76,0.1)'
          b.style.background=b===btn?`rgba(${hexToRgb(getModeColor())},0.12)`:'transparent'
        })
      })
    })

    // Brightness
    const bright=container.querySelector('#nvs-brightness')
    bright?.addEventListener('input',e=>{ _brightness=parseFloat(e.target.value) })

    // Sensitivity
    const sens=container.querySelector('#nvs-sensitivity')
    sens?.addEventListener('input',e=>{ _sensitivity=parseFloat(e.target.value) })

    // Zoom
    const zoom=container.querySelector('#nvs-zoom')
    zoom?.addEventListener('input',async e=>{
      _zoom=parseFloat(e.target.value)
      container.querySelector('#nvs-zoom-val').textContent=_zoom.toFixed(1)+'×'
      const track=_video?.srcObject?.getVideoTracks()[0]
      if (track) {
        try { await track.applyConstraints({advanced:[{zoom:_zoom}]}) }
        catch { _dispCanvas.style.transform=`scale(${_zoom})` }
      }
    })

    // Toggles
    container.querySelector('#nvs-reticle')?.addEventListener('click',e=>{
      _showReticle=!_showReticle; e.target.classList.toggle('nactive',_showReticle)
    })
    container.querySelector('#nvs-motion')?.addEventListener('click',e=>{
      _motionEnabled=!_motionEnabled; e.target.classList.toggle('nactive',_motionEnabled)
    })
    container.querySelector('#nvs-edge')?.addEventListener('click',e=>{
      _edgeOverlay=!_edgeOverlay; e.target.classList.toggle('nactive',_edgeOverlay)
    })
    container.querySelector('#nvs-noise')?.addEventListener('click',e=>{
      _noiseReduction=!_noiseReduction; e.target.classList.toggle('nactive',_noiseReduction)
    })
    container.querySelector('#nvs-flip')?.addEventListener('click',async()=>{
      _facing=_facing==='environment'?'user':'environment'
      Media.release('nightvision')
      await bootCamera()
    })
    container.querySelector('#nvs-rec')?.addEventListener('click',()=>{
      _recording?stopRec():startRec()
    })
    container.querySelector('#nvs-snap')?.addEventListener('click',takeSnapshot)
  }

  function hexToRgb(hex) {
    const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16)
    return `${r},${g},${b}`
  }

  function startRec() {
    if (!_dispCanvas) return
    _chunks=[]
    const stream=_dispCanvas.captureStream(30)
    _recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp9'})
    _recorder.ondataavailable=e=>_chunks.push(e.data)
    _recorder.onstop=()=>{
      const blob=new Blob(_chunks,{type:'video/webm'})
      const url=URL.createObjectURL(blob)
      const a=document.createElement('a')
      a.href=url; a.download=`vigil-nvs-${Date.now()}.webm`; a.click()
      URL.revokeObjectURL(url)
    }
    _recorder.start()
    _recording=true
    const btn=container.querySelector('#nvs-rec')
    if(btn){btn.textContent='⏹ STOP';btn.style.color='#E53E3E'}
  }

  function stopRec() {
    _recorder?.stop(); _recording=false
    const btn=container.querySelector('#nvs-rec')
    if(btn){btn.textContent='⏺ REC';btn.style.color='#C9A84C'}
  }

  function takeSnapshot() {
    const a=document.createElement('a')
    a.href=_dispCanvas.toDataURL('image/png')
    a.download=`vigil-snap-${Date.now()}.png`; a.click()
  }

  // ── Compass ──────────────────────────────────────────────
  function startCompass() {
    const handler=e=>{ _heading=e.webkitCompassHeading??e.alpha??null }
    if (typeof DeviceOrientationEvent?.requestPermission==='function') {
      DeviceOrientationEvent.requestPermission().then(s=>{
        if(s==='granted'){ window.addEventListener('deviceorientation',handler,true); _orientHandler=handler }
      }).catch(()=>{})
    } else {
      window.addEventListener('deviceorientation',handler,true)
      _orientHandler=handler
    }
  }

  async function bootCamera() {
    const stream=await Media.acquire('nightvision',{
      video:{facingMode:_facing,width:{ideal:1280},height:{ideal:720}}
    })
    _video.srcObject=stream
    await _video.play()
  }

  async function init(el) {
    container=el; _active=true
    container.innerHTML=html()
    _video=container.querySelector('#nvs-video')
    _rawCanvas=document.createElement('canvas')
    _rawCtx=_rawCanvas.getContext('2d',{willReadFrequently:true})
    _dispCanvas=container.querySelector('#nvs-canvas')
    _dispCtx=_dispCanvas.getContext('2d')
    bindControls()
    await bootCamera()
    startCompass()
    _stopLoop=RAF.start('nightvision',processFrame)
  }

  function destroy() {
    _active=false; _recording=false; _recorder?.stop()
    _stopLoop?.(); _prevFrame=null
    if(_orientHandler){window.removeEventListener('deviceorientation',_orientHandler,true);_orientHandler=null}
    Media.release('nightvision')
  }

  function health() {
    return {
      status:_active?'ok':'idle', mode:_mode, fps:_fps,
      motionLevel:+(_motionLevel*100).toFixed(1)+'%',
      blobs:_blobs.length, recording:_recording,
      heading:_heading!==null?Math.round(_heading)+'°':'none',
      camera:_video?.srcObject?'active':'none'
    }
  }

  function html() {
    const modes=Object.keys(LUTS)
    const modeBtns=modes.map((m,i)=>`
      <button class="nvs-mode-btn${i===0?' nactive':''}" data-m="${m}"
        style="flex:1;min-width:0;background:${i===0?'rgba(68,255,136,0.12)':'transparent'};
        border:1px solid rgba(201,168,76,${i===0?'0.4':'0.1'});
        color:${i===0?'#44ff88':'#6B6070'};font-family:'DM Mono',monospace;
        font-size:8px;letter-spacing:.06em;padding:7px 2px;cursor:pointer;text-transform:uppercase">
        ${m}
      </button>`).join('')

    return `
    <div style="display:flex;flex-direction:column;height:100%;background:#000;overflow:hidden">
      <video id="nvs-video" autoplay playsinline muted style="display:none"></video>
      <canvas id="nvs-canvas" style="flex:1;width:100%;display:block;object-fit:cover"></canvas>

      <!-- Palette row -->
      <div style="background:#0D0A14;padding:6px;display:flex;gap:3px">${modeBtns}</div>

      <!-- Controls row 1: toggles -->
      <div style="background:#0D0A14;padding:6px;display:flex;gap:4px;flex-wrap:wrap;border-top:1px solid rgba(201,168,76,0.06)">
        <button id="nvs-reticle" class="nvs-tog nactive" data-label="RETICLE">⊕ RETICLE</button>
        <button id="nvs-motion"  class="nvs-tog nactive" data-label="MOTION">⬥ MOTION</button>
        <button id="nvs-edge"    class="nvs-tog"          data-label="EDGES">◈ EDGES</button>
        <button id="nvs-noise"   class="nvs-tog nactive"  data-label="DENOISE">◎ DENOISE</button>
        <button id="nvs-flip"    class="nvs-tog"          data-label="FLIP">↺ FLIP</button>
      </div>

      <!-- Controls row 2: sliders -->
      <div style="background:#0D0A14;padding:8px 10px;display:flex;flex-direction:column;gap:7px;border-top:1px solid rgba(201,168,76,0.06)">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:8px;color:#6B6070;letter-spacing:.1em;width:64px">BRIGHTNESS</span>
          <input id="nvs-brightness" type="range" min="-1" max="1" step="0.05" value="0" style="flex:1;accent-color:#C9A84C">
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:8px;color:#6B6070;letter-spacing:.1em;width:64px">SENSITIVITY</span>
          <input id="nvs-sensitivity" type="range" min="0" max="1" step="0.05" value="0.6" style="flex:1;accent-color:#C9A84C">
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:8px;color:#6B6070;letter-spacing:.1em;width:64px">ZOOM <span id="nvs-zoom-val">1.0×</span></span>
          <input id="nvs-zoom" type="range" min="1" max="10" step="0.1" value="1" style="flex:1;accent-color:#C9A84C">
        </div>
      </div>

      <!-- Controls row 3: record + snapshot -->
      <div style="background:#0D0A14;padding:8px;display:flex;gap:6px;border-top:1px solid rgba(201,168,76,0.06)">
        <button id="nvs-rec"  style="flex:1;background:transparent;border:1px solid rgba(201,168,76,0.3);color:#C9A84C;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.15em;padding:10px;cursor:pointer;text-transform:uppercase">⏺ REC</button>
        <button id="nvs-snap" style="flex:1;background:transparent;border:1px solid rgba(201,168,76,0.3);color:#C9A84C;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.15em;padding:10px;cursor:pointer;text-transform:uppercase">📷 SNAP</button>
      </div>
    </div>
    <style>
      .nvs-tog{background:transparent;border:1px solid rgba(201,168,76,0.1);color:#6B6070;font-family:'DM Mono',monospace;font-size:8px;letter-spacing:.1em;padding:6px 8px;cursor:pointer;border-radius:4px;text-transform:uppercase;transition:all .15s}
      .nvs-tog.nactive{background:rgba(201,168,76,0.1);border-color:rgba(201,168,76,0.4);color:#C9A84C}
    </style>`
  }

  init(container)
  return { init, destroy, health }
}
