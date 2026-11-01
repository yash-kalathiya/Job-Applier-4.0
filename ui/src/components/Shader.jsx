import { useEffect, useRef } from 'react'

/* Live GPU background: domain-warped noise, flowing like liquid light, in Job Applier blues.
   Reacts to the pointer. Raw WebGL (no libraries), ~60fps, pauses when the tab is hidden. */

const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`
const FRAG = `
precision highp float;
uniform vec2 r; uniform float t; uniform vec2 m; uniform float hot;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(h(i), h(i+vec2(1,0)), f.x), mix(h(i+vec2(0,1)), h(i+vec2(1,1)), f.x), f.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; mat2 R = mat2(1.6, 1.2, -1.2, 1.6); for (int i = 0; i < 5; i++){ v += a*n(p); p = R*p; a *= 0.5; } return v; }
void main(){
  vec2 uv = gl_FragCoord.xy / r.xy;
  vec2 p = (gl_FragCoord.xy - 0.5*r.xy) / r.y;
  float T = t * 0.06;
  vec2 mm = (m - 0.5) * vec2(r.x/r.y, 1.0);
  float d = length(p - mm);
  p += 0.08 * normalize(p - mm + 1e-4) * exp(-d*3.0) * hot;          // the light bends around the cursor
  vec2 q = vec2(fbm(p*1.4 + vec2(0.0, T)), fbm(p*1.4 + vec2(5.2, 1.3) - T));
  vec2 w = vec2(fbm(p*1.6 + 3.0*q + vec2(1.7, 9.2) + 0.7*T), fbm(p*1.6 + 3.0*q + vec2(8.3, 2.8) - 0.5*T));
  float f = fbm(p*1.2 + 3.5*w);
  vec3 navy = vec3(0.008, 0.035, 0.12), royal = vec3(0.07, 0.25, 0.85), cyan = vec3(0.18, 0.75, 1.0), ice = vec3(0.85, 0.95, 1.0), violet = vec3(0.42, 0.33, 1.0);
  vec3 c = mix(navy, royal, smoothstep(0.15, 0.65, f));
  c = mix(c, violet, smoothstep(0.55, 0.9, length(q)) * 0.35);
  c = mix(c, cyan, smoothstep(0.62, 0.95, f) * 0.85);
  c += ice * pow(smoothstep(0.7, 1.0, f), 3.0) * 0.8;                  // bright crests
  c += cyan * exp(-d*4.0) * 0.25 * hot;                                // cursor glow
  c *= 0.75 + 0.35*smoothstep(1.1, 0.0, uv.y);                         // darker at the top
  c += (h(gl_FragCoord.xy + t) - 0.5) * 0.035;                         // film grain
  gl_FragColor = vec4(c, 1.0);
}`

export function Shader({ className, style }) {
  const ref = useRef(null)
  useEffect(() => {
    const cv = ref.current
    const gl = cv.getContext('webgl', { antialias: false, premultipliedAlpha: false })
    if (!gl) { cv.style.background = 'linear-gradient(180deg,#031740,#0a3a99 50%,#1f6fe5)'; return }
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.warn('[job-applier shader]', gl.getShaderInfoLog(s)); return s }
    const pr = gl.createProgram()
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(pr); gl.useProgram(pr)
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(pr, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
    const U = k => gl.getUniformLocation(pr, k)
    const ur = U('r'), ut = U('t'), um = U('m'), uh = U('hot')
    let mx = 0.7, my = 0.6, tx = 0.7, ty = 0.6, heat = 0, target = 0, raf, t0 = performance.now()
    const SCALE = 0.38  // liquid light upscales beautifully; this keeps it smooth on any GPU
    const size = () => { const w = Math.max(1, cv.clientWidth), hgt = Math.max(1, cv.clientHeight)
      cv.width = Math.round(w * SCALE); cv.height = Math.round(hgt * SCALE); gl.viewport(0, 0, cv.width, cv.height) }
    const ro = new ResizeObserver(size); ro.observe(cv)
    let shown = false
    const move = e => { const b = cv.getBoundingClientRect(); tx = (e.clientX - b.left) / b.width; ty = 1 - (e.clientY - b.top) / b.height; target = (ty > -0.2 && ty < 1.2) ? 1 : 0 }
    const frame = now => {
      mx += (tx - mx) * 0.05; my += (ty - my) * 0.05; heat += (target - heat) * 0.04
      gl.uniform2f(ur, cv.width, cv.height); gl.uniform1f(ut, (now - t0) / 1000); gl.uniform2f(um, mx, my); gl.uniform1f(uh, heat)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      if (!shown) { shown = true; cv.style.opacity = 1 }
      raf = requestAnimationFrame(frame)
    }
    size(); window.addEventListener('resize', size); window.addEventListener('pointermove', move)
    const vis = () => { cancelAnimationFrame(raf); if (!document.hidden) raf = requestAnimationFrame(frame) }
    document.addEventListener('visibilitychange', vis)
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener('resize', size); window.removeEventListener('pointermove', move)
      document.removeEventListener('visibilitychange', vis); gl.getExtension('WEBGL_lose_context')?.loseContext() }
  }, [])
  return <canvas ref={ref} className={className} style={{ width: '100%', height: '100%', display: 'block', opacity: 0, transition: 'opacity 1.2s ease', ...style }} />
}
