# Custom behaviour checks (scenarios)

Use a scenario to turn a **suspicion** into a **proven** problem, then let a fix prove it solved it.
Add it with `verify_fix.py add-check --site site --work work --scenario checks/NAME.json`. The check is appended to `site/site-tests.json` (fixes can never edit that file).

- On adding, the check must give a stable `pass` or `fail` and no other check may change.
- `fail` on adding = the suspicion is now **proven**. Then a `kind: "fix"` proposal can target `scenario:<id>`.
- `pass` on adding = the suspicion was **wrong**. Report it as refuted; the check stays as a regression guard.
- Write the check to describe the **correct** behaviour (what should happen), not the bug.
- Ids are permanent. Never "fix" a failing check by changing the check: write a new id only if the first one was wrong, and say so in the report.

## Format

```json
{
  "id": "empty-cart-blocked",
  "page": "index.html",
  "desc": "Ordering with an empty cart sends nothing and tells the visitor why",
  "source": "inspector SUS-2",
  "viewport": "desktop",
  "offline": [],
  "steps": [
    {"fill": "input[name=name]", "value": "Sara"},
    {"submit": "#order-form"}
  ],
  "expect": [
    {"no_request": "POST /api/order"},
    {"text": "#order-msg", "not_empty": true}
  ]
}
```

### Steps (exactly one key each, in order)
| step | meaning |
|---|---|
| `{"click": "css", "times": 1}` | real mouse click (fails if hidden/disabled) |
| `{"fill": "css", "value": "..."}` | type into an input/textarea |
| `{"select": "css", "value": "..."}` | choose an option |
| `{"check": "css"}` | tick a checkbox/radio |
| `{"submit": "form css"}` | click the form's submit button once (JS click: a disabled button does nothing) |
| `{"double_submit": "form css"}` | click the submit button twice instantly |
| `{"wait": 300}` | wait milliseconds |

Options: `"viewport": "mobile"` (375×667), `"offline": ["/api/order"]` (requests to these paths fail like a dropped network), `"settle_ms": 900` (wait after the steps).

### Expectations (exactly one key each; all must hold)
| expectation | passes when |
|---|---|
| `{"request": "POST /api/order"}` | at least one such request was sent (add `"count": 1` for an exact number) |
| `{"no_request": "POST /api/order"}` | no such request was sent |
| `{"body": "POST /api/order", "contains": "text"}` | a request body contains the text |
| `{"text": "css", "contains": "..."}` / `"equals"` / `"not_empty": true` | first matching element's visible text |
| `{"count_visible": "css", "equals": 2}` | number of visible matching elements |
| `{"visible": "css"}` / `{"hidden": "css"}` | visibility of the first match |
| `{"no_js_error": true}` | no uncaught JS error happened |

Method may be omitted (`"/api/order"` = any method). Requests are only those made after the page loaded.

## Good scenario habits
- One behaviour per scenario. Name it after the correct behaviour.
- Prefer stable selectors (ids, names) the site already has. If a fix must rename them, the scenario will break: that shows up as needs_review/regression, which is correct.
- Text expectations should use short fragments (`contains`) so harmless rewording does not break them, unless the exact text matters.
