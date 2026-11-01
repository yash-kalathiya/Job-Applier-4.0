/* Turns an agent's raw run log into what a person wants to know: what it's doing right now, and how far along it is. */

const STEPS = [
  [/next_jobs|queue/, 'Picking your next jobs'],
  [/claim/, 'Claiming a job'],
  [/get_job|job_questions/, 'Reading the posting'],
  [/tailor_prompt|tailor_apply|render_resume|ats_report/, 'Tailoring your resume'],
  [/playbook/, 'Learning this application site'],
  [/browser_navigate|tabs/, 'Opening the application'],
  [/browser_snapshot|take_screenshot|wait_for|find/, 'Reading the form'],
  [/browser_file_upload/, 'Uploading your resume'],
  [/answer_questions|get_answers|save_answer/, 'Answering from your bank'],
  [/fill_form|browser_type|select_option|browser_click|press_key|evaluate/, 'Filling in the form'],
  [/notify/, 'Flagging something for you'],
  [/log_application/, 'Logging the result'],
  [/pending_jobs/, 'Checking what you unblocked'],
]

const strip = s => s.replace(/\x1b\[[0-9;]*m/g, '')

export function parseRun(raw = '') {
  const log = strip(raw)
  const n = +(log.match(/apply to (\d+) jobs/)?.[1] || 0)
  const calls = [...log.matchAll(/mcp:\s+([\w-]+)\/(\w+)\s+started/g)].map(m => m[2])
  const last = calls[calls.length - 1] || ''
  const step = STEPS.find(([re]) => re.test(last))?.[1] || (log.trim() ? 'Getting ready' : '')
  // the agent's own short updates ("codex" blocks), newest last
  const notes = [...log.matchAll(/\ncodex\n([\s\S]*?)(?=\n(?:mcp:|exec|tokens used|codex\n|\d{4}-\d\d-\d\dT)|$)/g)]
    .map(m => m[1].trim()).filter(t => t && t.length < 400)
  const failed = /Failed to authenticate|model_not_found|not logged in/i.test(log)
  return { n, step, calls: calls.length, note: notes[notes.length - 1] || '', failed, clean: log }
}
