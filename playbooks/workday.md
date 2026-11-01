# Workday (<tenant>.wd<N>.myworkdayjobs.com)

- Requires an account per company. Job Applier 4.0 never creates accounts or types passwords: if the user is not signed
  in, stop (Needs User) and leave the sign-in page open. Once they are signed in, continue.
- First application at a tenant: "Autofill with Resume". Later ones: "Use My Last Application"
  (`.../apply/useMyLastApplication`), which carries everything over; then only review each step.
- Dropdowns are buttons with listboxes (`button[aria-haspopup=listbox]`): click, then click the exact
  `[role=option]`. "How did you hear" is a nested menu: click a category, then the leaf.
- Degree in progress: some tenants want "Degree in Progress" rather than "Bachelor's" (Bachelor's = conferred).
- Multi-select search inputs (locations, skills): type, wait, click the option, Escape.
- Self-identify page: name + today's date (MM/DD/YYYY segmented: click month, type digits) + disability box.
- Review page lists everything: verify, then Submit (only with auto_submit) and confirm "Application Submitted".
- Old drafts show as "Not Submitted" on Candidate Home: the posting may have closed; check before resuming.
