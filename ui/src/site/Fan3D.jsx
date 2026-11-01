import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

/* One resume becomes many: real paper sheets in studio light. Scrolled from 0 to 1, a single stack (your resume) fans out
   into an arc of versions, each tailored for one company, while the camera eases in. The pointer tilts the scene a little. */

const COMPANIES = [['Jane Street', 96], ['NVIDIA', 95], ['Google', 98], ['Meta', 96], [null, 0], ['Citadel', 94], ['Palantir', 97], ['Anduril', 94], ['Stripe', 95]]
const W = 0.85, H = 1.1   // a letter-size page, in scene units

function paper(company, fit, seed) {
  const c = document.createElement('canvas')
  c.width = 1020; c.height = 1320
  const g = c.getContext('2d')
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, c.width, c.height)
  const rnd = (() => { let s = seed * 9301 + 49297; return () => ((s = (s * 9301 + 49297) % 233280) / 233280) })()
  g.textAlign = 'center'
  g.fillStyle = '#111'; g.font = 'bold 54px Georgia, "Times New Roman", serif'
  g.fillText('ELON MUSK', c.width / 2, 132)
  g.fillStyle = '#555'; g.font = '600 25px -apple-system, Helvetica, Arial, sans-serif'
  g.fillText(company ? `Tailored for ${company}` : 'Aerospace · Electric Vehicles · Engineering', c.width / 2, 178)
  g.fillStyle = '#999'; g.font = '22px -apple-system, Helvetica, Arial, sans-serif'
  g.fillText('Tesla  ·  SpaceX  ·  Austin, TX', c.width / 2, 216)
  let y = 268
  for (const sec of ['EDUCATION', 'EXPERIENCE', 'PROJECTS', 'RESEARCH', 'SKILLS']) {
    g.textAlign = 'left'; g.fillStyle = '#222'; g.font = '600 24px Georgia, serif'
    g.fillText(sec, 82, y)
    g.fillStyle = '#222'; g.fillRect(82, y + 12, c.width - 164, 2)
    y += 44
    const rows = sec === 'EDUCATION' ? 2 : sec === 'SKILLS' ? 3 : 5
    for (let r = 0; r < rows; r++) {
      const head = sec !== 'SKILLS' && (r === 0 || (sec === 'EXPERIENCE' && r === 3))
      g.fillStyle = head ? '#2a2a2a' : '#c9c9cf'
      const w = head ? 360 + rnd() * 160 : 560 + rnd() * 300
      g.fillRect(head ? 82 : 112, y - 14, w, head ? 14 : 11)
      if (!head && company && rnd() > 0.55) { g.fillStyle = '#0071e3'; g.fillRect(112 + w * (0.15 + rnd() * 0.4), y - 14, 70 + rnd() * 70, 11) }   // the parts rewritten for this job
      if (head) { g.fillStyle = '#9a9aa0'; g.fillRect(c.width - 82 - 150, y - 13, 150, 11) }
      y += head ? 34 : 28
    }
    y += 18
  }
  if (company) {   // the match badge, top right
    g.fillStyle = fit >= 96 ? '#28a745' : '#0071e3'
    g.beginPath(); g.roundRect(c.width - 230, 40, 178, 52, 26); g.fill()
    g.fillStyle = '#fff'; g.font = '700 26px -apple-system, Helvetica, Arial, sans-serif'; g.textAlign = 'center'
    g.fillText(`${fit}% match`, c.width - 141, 75)
  }
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  t.anisotropy = 8
  return t
}

const clamp = v => Math.min(1, Math.max(0, v))
const ease = t => 1 - Math.pow(1 - t, 3)

function Sheet({ i, n, company, fit, progress, pointer }) {
  const ref = useRef()
  const mats = useMemo(() => {
    const edge = new THREE.MeshStandardMaterial({ color: '#f2f2f4', roughness: 0.7 })
    const face = new THREE.MeshStandardMaterial({ map: paper(company, fit, i + 1), roughness: 0.5, emissive: "#ffffff", emissiveIntensity: 0.08 })
    const back = new THREE.MeshStandardMaterial({ color: '#fafafa', roughness: 0.7 })
    return [edge, edge, edge, edge, face, back]
  }, [company, fit, i])
  const mid = (n - 1) / 2
  const a = (i - mid) * 0.3
  useFrame(() => {
    const s = progress.current
    const t = ease(clamp(s * 1.35 - Math.abs(i - mid) * 0.06))
    const R = 2.2
    // stacked (a neat ream, your resume on top) -> fanned (an arc of tailored versions around you)
    const sx = 0, sy = -Math.abs(i - mid) * 0.008, sz = -Math.abs(i - mid) * 0.02
    const fx = Math.sin(a) * R, fy = 0.04 * Math.cos(a * 2) - 0.02, fz = (Math.cos(a) - 1) * R
    const m = ref.current
    m.position.set(sx + (fx - sx) * t, sy + (fy - sy) * t, sz + (fz - sz) * t + (i === Math.round(mid) ? 0.04 : 0))
    m.rotation.set(-0.06 * t, -a * t * 0.92 + pointer.current.x * 0.05, (i - mid) * 0.012 * (1 - t))
  })
  return <mesh ref={ref} castShadow receiveShadow material={mats}><boxGeometry args={[W, H, 0.004]} /></mesh>
}

function Rig({ progress, pointer }) {
  useFrame(({ camera, size }) => {
    const s = ease(clamp(progress.current))
    const back = Math.max(1, 0.95 / (size.width / size.height))   // narrow (phone) screens step back to see the whole fan
    camera.position.x += ((pointer.current.x * 0.25) - camera.position.x) * 0.05
    camera.position.y += ((0.12 + pointer.current.y * 0.12) - camera.position.y) * 0.05
    camera.position.z = (3.9 - s * 0.35) * back
    camera.lookAt(0, 0.02, -0.3 * s)
  })
  return null
}

export default function Fan3D({ progress }) {
  const pointer = useRef({ x: 0, y: 0 })
  return (
    <div className="h-full w-full" onPointerMove={e => {
      const r = e.currentTarget.getBoundingClientRect()
      pointer.current = { x: ((e.clientX - r.left) / r.width - 0.5) * 2, y: -((e.clientY - r.top) / r.height - 0.5) * 2 }
    }}>
      <Canvas shadows flat dpr={[1, 2]} camera={{ position: [0, 0.12, 3.9], fov: 30 }} gl={{ antialias: true, alpha: true }}>
        <ambientLight intensity={1.4} />
        <hemisphereLight args={['#ffffff', '#e4e7ee', 0.45]} />
        <directionalLight position={[-2.5, 4, 3]} intensity={1.25} castShadow shadow-mapSize={[2048, 2048]} shadow-radius={8}
          shadow-camera-left={-4} shadow-camera-right={4} shadow-camera-top={4} shadow-camera-bottom={-4} />
        <directionalLight position={[3, 1, 2]} intensity={0.35} />
        {COMPANIES.map(([c, f], i) => <Sheet key={i} i={i} n={COMPANIES.length} company={c} fit={f} progress={progress} pointer={pointer} />)}
        <mesh rotation-x={-Math.PI / 2} position={[0, -H / 2 - 0.02, -0.6]} receiveShadow>
          <planeGeometry args={[14, 14]} /><shadowMaterial opacity={0.12} />
        </mesh>
        <Rig progress={progress} pointer={pointer} />
      </Canvas>
    </div>
  )
}
