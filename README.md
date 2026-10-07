# Change Order Extraction Pipeline

A conservative command-line tool that extracts explicitly labeled fields from change-order PDFs or plain text and writes JSON. Each extracted value includes source evidence, page number, and a confidence score. Conflicting repeated values are left unresolved instead of silently choosing one.

## Run

Requires Python 3.10 or newer.

```bash
python -m venv .venv
```

Activate the environment, then install and run:

```bash
pip install -e .
change-order-extract path/to/change-order.pdf -o result.json
change-order-extract path/to/change-order.txt
```

The command uses `pypdf` for text-based PDFs. Image-only/scanned PDFs need OCR first; this tool does not pretend to read text that is not present in the PDF text layer.

Run the automated checks after installation with `python -m unittest discover -s tests -v`. The suite includes a text fixture, a real text-layer PDF fixture exercised through the CLI, and an intentionally malformed PDF; all are controlled examples rather than customer documents.

Run the field-level benchmark with `python scripts/evaluate.py`. It reports exact-match results and mismatches by field for the checked-in fixtures. The current 100% fixture score is a regression result on these controlled examples only, not an estimate of performance on Sledge documents.

## Output contract

`fields` contains a fixed set of keys. Each field has `value`, `confidence`, `evidence`, and `page`. Unknown values are `null` with confidence `0`; labeled but unparseable values retain their evidence and receive low confidence. Repeated contradictory values are `null` with low confidence and the conflicting evidence retained. Dates are emitted as ISO `YYYY-MM-DD`; ambiguous numeric dates are left null with their evidence retained. Monetary values are numeric and preserve sign when the source explicitly indicates a credit or parenthesized amount. The output contract is described in `schema.json`, and runtime type checks populate `validation`.

The confidence values are transparent rule-based indicators, not calibrated probabilities. A direct, parseable value receives `0.95`; a value on the following line receives `0.85`; a numeric date with one valid interpretation receives `0.72`; a labeled value that cannot be parsed receives `0.25`; conflicting values receive `0.20`; and absent fields receive `0`. Treat these as review priorities, not guarantees of correctness.

The output covers change-order number, project, owner, contractor, issue date, title, description, reason, cost change, original and revised contract sums, schedule impact in days, status, requester, and approver. Extend the aliases and schema together when a target customer requires additional fields.

## Approach

See [WRITEUP.md](WRITEUP.md) for the concise approach and failure-mode summary.

1. Extract text page by page (PDF) or read UTF-8 text.
2. Match a controlled set of common field labels, keeping extraction conservative so unsupported values are not inferred.
3. Normalize dates, amounts, and schedule-day counts where parsing is unambiguous.
4. Validate output against the fixed field types and retain the exact matching line(s) as evidence.
5. If repeated values disagree, return `null` for that field and preserve all conflicting evidence for human review.

The pipeline intentionally does not calculate a revised contract value from a base amount and a change amount, infer approval from a signature image, or guess missing data from context.

## Failure modes and limits

- Scanned/image-only PDFs have no text layer and require OCR. OCR errors can corrupt names, amounts, dates, and identifiers.
- Templates with labels outside the alias list, unusual layouts, tables, handwriting, or values split across columns may be missed or attached incorrectly.
- Numeric dates such as `03/04/2025` are ambiguous across locales and are left unresolved.
- A value may be labeled but still be stale, superseded, or semantically different from the expected field. Evidence supports review; it does not establish business truth.
- Repeated fields with conflicting values are surfaced as unresolved. The tool does not decide which revision is authoritative.
- Confidence is heuristic and has not been calibrated on a representative labeled dataset. It should not drive unattended approvals or payments.

Before production use, evaluate on representative, permissioned change orders; measure field-level precision/recall and calibration; add OCR and layout-specific handling where needed; and route low-confidence or conflicting fields to human review.
