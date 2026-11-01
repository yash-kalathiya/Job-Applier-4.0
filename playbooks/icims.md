# iCIMS (careers-<co>.icims.com)

- The form is inside an iframe (`#icims_content_iframe`): read and act inside it.
- Most iCIMS portals require sign-in by email and often an hCaptcha: that is a hard stop for Job Applier 4.0. Fill the
  email only if the user asked, never solve the captcha; hand the tab to the user, then continue after they
  sign in.
- Steps are paginated (Contact, Resume, Questions, EEO, Review). Upload the PDF on the resume step, verify the
  parsed fields, answer questions from the bank, and stop at Review unless auto_submit.
