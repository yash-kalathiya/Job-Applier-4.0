export async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (r.status === 401 && !path.startsWith('/api/auth')) { location.reload(); throw new Error('Sign in to Job Applier 4.0') }
  const j = await r.json()
  if (j && j.error) throw new Error(j.error)
  return j
}
/* Links from job boards or the agent: only real web pages, never javascript: or other schemes. */
export const safeUrl = u => (/^https?:\/\//i.test(u || '') ? u : undefined)
export const fileUrl = p => '/file?path=' + encodeURIComponent(p)
