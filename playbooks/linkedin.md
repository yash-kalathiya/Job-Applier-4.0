# LinkedIn Easy Apply

- Uses the user's LinkedIn session; never sign in for them.
- The modal pre-fills work experience from the profile: check each entry against the vault (title, company,
  dates, location). Profile imports often shift descriptions between roles: fix them in the form (and tell the
  user to fix the profile, since recruiters compare the two).
- Upload the tailored PDF on the resume step and make sure it is the selected one.
- Questions re-render after every click (element refs go stale): take a screenshot, click by position, take
  another screenshot to verify. Watch for mis-clicks on adjacent checkboxes ("previously worked at...").
- "Do you work/have you worked at LinkedIn or Microsoft": gig or contract work done through a third-party
  platform is "Not Applicable"; only direct or agency-placed work counts.
- Many Easy Apply forms have no captcha; submit only with auto_submit, else stop on the Review page.
