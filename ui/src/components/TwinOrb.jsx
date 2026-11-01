import { useEffect, useRef } from 'react'

/* The twin, as an object: two liquid glass spheres (you, and your twin) that orbit, stretch toward each other and
   merge, rendered by raymarching a smooth-union of two SDF spheres. Iridescent fresnel, fake environment
   reflections in Job Applier blues. Follows the pointer. Raw WebGL, low internal resolution, pauses when hidden. */

const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`
const FRAG = `
precision highp float;
uniform vec2 r; uniform float t; uniform vec2 m;
float smin(float a, float b, float k){ float h = clamp(0.5 + 0.5*(b-a)/k, 0.0, 1.0); return mix(b, a, h) - k*h*(1.0-h); }
vec3 A, B;
float map(vec3 p){
  float a = length(p - A) - 0.62;
  float b = length(p - B) - 0.5;
  float wob = 0.035*sin(p.x*6.0 + t*1.3)*sin(p.y*5.0 - t*1.1)*sin(p.z*4.0 + t);
  return smin(a, b, 0.55) + wob;
}
vec3 nor(vec3 p){ vec2 e = vec2(0.0015, 0.0); return normalize(vec3(map(p+e.xyy)-map(p-e.xyy), map(p+e.yxy)-map(p-e.yxy), map(p+e.yyx)-map(p-e.yyx))); }
vec3 env(vec3 d){
  float y = d.y*0.5 + 0.5;
  vec3 c = mix(vec3(0.02, 0.05, 0.16), vec3(0.12, 0.35, 1.0), smoothstep(0.0, 1.0, y));
  c += vec3(0.6, 0.85, 1.0) * pow(max(0.0, dot(d, normalize(vec3(0.5, 0.8, 0.4)))), 24.0) * 2.2;   // key light
  c += vec3(0.55, 0.4, 1.0) * pow(max(0.0, dot(d, normalize(vec3(-0.8, 0.1, 0.5)))), 6.0) * 0.6;   // violet rim
  c += vec3(0.2, 0.9, 1.0) * smoothstep(0.92, 1.0, sin(d.x*9.0 + t*0.6) * 0.5 + 0.5) * 0.25;      // light bars
  return c;
}
void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5*r) / r.y;
  float s = t * 0.55;
  float d = 0.62 + 0.18*sin(s*0.7);                     // they drift apart and back together
  A = vec3(cos(s)*d, sin(s*1.3)*0.18, sin(s)*d*0.6);
  B = -A * 0.95 + vec3(0.0, 0.05, 0.0);
  vec3 ro = vec3(0.0, 0.0, 4.9);
  vec2 mm = (m - 0.5) * 0.6;
  float cy = cos(mm.x), sy = sin(mm.x), cx = cos(-mm.y), sx = sin(-mm.y);
  vec3 rd = normalize(vec3(uv, -1.75));
  rd.xz = mat2(cy, -sy, sy, cy) * rd.xz; ro.xz = mat2(cy, -sy, sy, cy) * ro.xz;
  rd.yz = mat2(cx, -sx, sx, cx) * rd.yz; ro.yz = mat2(cx, -sx, sx, cx) * ro.yz;
  float tt = 0.0, hit = 0.0;
  for (int i = 0; i < 72; i++){ vec3 p = ro + rd*tt; float h = map(p); if (h < 0.001){ hit = 1.0; break; } tt += h; if (tt > 10.0) break; }
  vec3 col = vec3(0.0); float alpha = 0.0;
  if (hit > 0.5){
    vec3 p = ro + rd*tt, n = nor(p);
    float fr = pow(1.0 - max(0.0, dot(n, -rd)), 3.0);
    vec3 refl = env(reflect(rd, n));
    vec3 refr = env(refract(rd, n, 0.75)) * vec3(0.55, 0.75, 1.0);
    vec3 irid = 0.5 + 0.5*cos(6.2831*(fr*1.2 + vec3(0.0, 0.33, 0.67)) + t*0.3);
    col = mix(refr, refl, 0.25 + 0.75*fr) + irid * fr * 0.35;
    col += vec3(1.0) * pow(max(0.0, dot(reflect(rd, n), normalize(vec3(0.5, 0.8, 0.4)))), 80.0) * 1.5;
    alpha = 1.0;
  }
  float glow = exp(-length(uv)*2.4) * 0.35;
  col += vec3(0.25, 0.5, 1.0) * glow * (1.0 - alpha);
  alpha = max(alpha, glow);
  gl_FragColor = vec4(col, alpha);
}`

export function TwinOrb({ className, style }) {
  const ref = useRef(null)
  useEffect(() => {
    const cv = ref.current
    const gl = cv.getContext('webgl', { premultipliedAlpha: false, alpha: true, antialias: false })
    if (!gl) return
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.warn('[job-applier shader]', gl.getShaderInfoLog(s)); return s }
    const pr = gl.createProgram()
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(pr); gl.useProgram(pr)
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer())
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(pr, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
    const ur = gl.getUniformLocation(pr, 'r'), ut = gl.getUniformLocation(pr, 't'), um = gl.getUniformLocation(pr, 'm')
    const SCALE = 0.55
    const size = () => { cv.width = Math.max(1, Math.round(cv.clientWidth * SCALE)); cv.height = Math.max(1, Math.round(cv.clientHeight * SCALE)); gl.viewport(0, 0, cv.width, cv.height) }
    const ro = new ResizeObserver(size); ro.observe(cv)
    let mx = 0.5, my = 0.5, tx = 0.5, ty = 0.5, raf, t0 = performance.now(), shown = false
    const move = e => { tx = e.clientX / innerWidth; ty = e.clientY / innerHeight }
    const frame = now => {
      mx += (tx - mx) * 0.04; my += (ty - my) * 0.04
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT)
      gl.uniform2f(ur, cv.width, cv.height); gl.uniform1f(ut, (now - t0) / 1000); gl.uniform2f(um, mx, my)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      if (!shown) { shown = true; cv.style.opacity = 1 }
      raf = requestAnimationFrame(frame)
    }
    size(); window.addEventListener('pointermove', move, { passive: true })
    const vis = () => { cancelAnimationFrame(raf); if (!document.hidden) raf = requestAnimationFrame(frame) }
    document.addEventListener('visibilitychange', vis)
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener('pointermove', move); document.removeEventListener('visibilitychange', vis)
      gl.getExtension('WEBGL_lose_context')?.loseContext() }
  }, [])
  return <canvas ref={ref} className={className} style={{ width: '100%', height: '100%', display: 'block', opacity: 0, transition: 'opacity 1.4s ease', ...style }} />
}
