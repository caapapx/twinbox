# TB13 fixed business-case inventory

`cases.json` is a **local, non-sensitive evaluation inventory** for feature 013.
It freezes the required 24 case slots as 14 opaque private-history handles and
10 deterministic synthetic classification cases. It intentionally contains no
real mail, headers, locators, snippets, bodies, attachments, source grants, or
human gold labels.

Run the evaluator with:

```bash
.venv/bin/python tests/evaluations/tb13_business_cases.py
```

The 14 private-history reports remain `blocked` and the complete suite remains
`decision_eligible: false` until an authorized business owner provides the
private source material and signed gold results outside this repository. The 10
synthetic cases only prove local deterministic contract behavior; they are not
ROI, real-mail, production, or source-grant evidence.
