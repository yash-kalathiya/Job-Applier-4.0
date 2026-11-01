# Ashby (jobs.ashbyhq.com/<org>/<id>/application)

- JS value-setting does NOT register. For every text field: scrollIntoView(center), real click on it,
  select all + Delete, type, Tab. Typing a value identical to the current one fires no change: clear first.
- Resume autofill can wipe Name/Email after you type them: upload first, wait ~5s, then fill Name/Email.
- **Yes/No questions are buttons.** A click can look selected without registering: click the OPPOSITE
  answer, then the intended one. Verify by background color.
- Radios/checkboxes: click the `<label>` at its real coordinates (scroll into view first).
- Location = combobox: click, type the city, click the suggestion.
- **Click Submit ONCE.** Resubmit only after a visible "Missing entry" error you fixed. Silent click, or
  "flagged as possible spam" = STOP, log Needs User, and pause Ashby for this session.
- Success text: "Thanks for applying", "Application submitted" or "Thank you for submitting".
- "Maximum number of applications" = that company's cap; stop applying there.
