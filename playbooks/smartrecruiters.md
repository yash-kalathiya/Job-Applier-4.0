# SmartRecruiters (jobs.smartrecruiters.com/<company>/<id>)

- On the posting page, the "I'm interested" link goes to the one-click form; navigate to its href directly.
- The form lives in shadow DOM: normal element search can't see it. Walk `shadowRoot`s to find inputs; move
  the resume `input[type=file]` to document.body with a visible style and an aria-label, then upload to it.
- Resume parse fills name/email/phone/experience/education ~5-15s later and can WIPE typed fields. Wait until
  the Experience section appears, then type Confirm email, LinkedIn, website. Delete bogus parsed education
  rows (e.g. a "school" made of award names).
- The first click+type after the parse often doesn't stick: verify values via the shadow-DOM walker; redo.
- Screening page: search-selects first (click, type to filter, click option, wait 1s), screenshot, then
  radios. An unselected search-select adds an error label that shifts every radio below it.
- Privacy checkbox at the bottom, then Submit; success page says the application was sent.
