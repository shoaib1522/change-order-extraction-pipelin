"""Conservative extraction: every non-null value is tied to source evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Candidate:
    value: Any
    evidence: str
    page: int | None
    confidence: float = 0.95


# Aliases are deliberately explicit. Broad semantic guessing tends to create
# plausible-looking but unsupported construction data.
ALIASES: dict[str, tuple[str, ...]] = {
    "change_order_number": ("change order number", "change order no", "change order #", "co number", "co no", "co #"),
    "project_name": ("project name", "project"),
    "owner": ("owner", "client"),
    "contractor": ("contractor", "general contractor"),
    "issue_date": ("issue date", "date issued", "change order date", "date"),
    "title": ("change order title", "title", "subject"),
    "description": ("description of change", "change description", "description", "scope of work", "scope"),
    "reason": ("reason for change", "change reason", "reason"),
    "cost_change": ("change order amount", "amount of change", "net change", "cost change", "change in contract sum", "change amount"),
    "original_contract_sum": ("original contract sum", "original contract value", "original contract amount"),
    "revised_contract_sum": ("revised contract sum", "new contract sum", "revised contract value", "new contract value"),
    "schedule_impact_days": ("schedule impact", "time extension", "extension of time", "days added", "schedule change"),
    "status": ("status", "approval status"),
    "requested_by": ("requested by", "prepared by", "submitted by"),
    "approved_by": ("approved by", "authorized by"),
}

FIELD_TYPES = {
    "change_order_number": "string", "project_name": "string", "owner": "string",
    "contractor": "string", "issue_date": "date", "title": "string",
    "description": "string", "reason": "string", "cost_change": "number",
    "original_contract_sum": "number", "revised_contract_sum": "number",
    "schedule_impact_days": "integer", "status": "string",
    "requested_by": "string", "approved_by": "string",
}


def _label_pattern() -> re.Pattern[str]:
    labels = sorted({a for values in ALIASES.values() for a in values}, key=len, reverse=True)
    return re.compile(r"^\s*(" + "|".join(re.escape(label) for label in labels) + r")\.?\s*(?::|#|\-)?\s*(.*?)\s*$", re.I)


LABEL_RE = _label_pattern()
ALIAS_TO_FIELD = {alias.casefold(): field for field, aliases in ALIASES.items() for alias in aliases}


def _parse_date(raw: str) -> str | None:
    value = raw.strip().rstrip(".,;")
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
               "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")
    parsed: dict[str, set[str]] = {}
    for fmt in formats:
        try:
            date = datetime.strptime(value, fmt).date().isoformat()
            parsed.setdefault(date, set()).add(fmt)
        except ValueError:
            pass
    if len(parsed) == 1:
        return next(iter(parsed))
    # A numeric date that can mean two different days is unsafe to normalize.
    return None


def _parse_number(raw: str) -> float | None:
    value = raw.strip()
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1].strip()
    value = re.sub(r"^(?:USD|US\$|\$)\s*", "", value, flags=re.I)
    value = re.sub(r"\s*(?:USD|dollars?)$", "", value, flags=re.I)
    value = re.sub(r"\s+(?:CR|credit)$", "", value, flags=re.I)
    match = re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", value, re.I)
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    if negative or re.search(r"\b(?:credit|cr)\b", raw, re.I):
        number = -abs(number)
    return int(number) if number.is_integer() else number


def _parse_schedule_days(raw: str) -> int | None:
    value = re.sub(r"\s+", " ", raw.strip().casefold())
    if re.search(r"\bno (?:schedule )?impact\b", value):
        return 0
    matches = re.findall(r"([+-]?\d+)\s*(calendar|working)?\s*(days?|weeks?)\b", value)
    if len(matches) != 1:
        return None
    amount_text, _day_kind, unit = matches[0]
    amount = int(amount_text)
    if unit.startswith("week"):
        return amount * 7
    return amount


def _parse_value(field: str, raw: str) -> Any:
    value = re.sub(r"\s+", " ", raw).strip(" \t:;,-")
    if not value:
        return None
    if field == "issue_date":
        return _parse_date(value)
    if field in {"cost_change", "original_contract_sum", "revised_contract_sum"}:
        return _parse_number(value)
    if field == "schedule_impact_days":
        return _parse_schedule_days(value)
    return value


def _collect_candidates(pages: list[str]) -> dict[str, list[Candidate]]:
    found = {field: [] for field in ALIASES}
    for page_number, page_text in enumerate(pages, start=1):
        # Many extracted PDF tables put several labeled cells on one line.
        # Pipes are a safe, explicit cell boundary; ordinary spaces are not.
        lines = [cell.strip() for raw_line in page_text.splitlines() for cell in raw_line.split("|")]
        index = 0
        while index < len(lines):
            line = lines[index]
            match = LABEL_RE.match(line)
            if not match:
                index += 1
                continue
            label, value = match.groups()
            field = ALIAS_TO_FIELD.get(label.casefold())
            if not field:
                index += 1
                continue
            evidence_lines = [line]
            confidence = 0.95
            if field in {"description", "reason"}:
                cursor = index + 1
                while cursor < len(lines) and lines[cursor].strip() and not LABEL_RE.match(lines[cursor]):
                    evidence_lines.append(lines[cursor].strip())
                    cursor += 1
                continuation = " ".join(evidence_lines[1:])
                value = " ".join(part for part in (value, continuation) if part).strip()
                index = cursor
            else:
                # Some forms put a label and its value on separate lines.
                if not value and index + 1 < len(lines) and lines[index + 1] and not LABEL_RE.match(lines[index + 1]):
                    value = lines[index + 1]
                    evidence_lines.append(lines[index + 1])
                    confidence = 0.85
                    index += 2
                else:
                    index += 1
            parsed = _parse_value(field, value)
            found[field].append(Candidate(parsed, " ".join(evidence_lines), page_number, confidence))
    return found


def _field_result(field: str, candidates: list[Candidate]) -> dict[str, Any]:
    if not candidates:
        return {"value": None, "confidence": 0.0, "evidence": None, "page": None}
    distinct = {str(candidate.value) for candidate in candidates if candidate.value is not None}
    if any(candidate.value is None for candidate in candidates):
        evidence = " | ".join(candidate.evidence for candidate in candidates)
        page = candidates[0].page if len(candidates) == 1 else None
        return {"value": None, "confidence": 0.25 if len(candidates) == 1 else 0.2, "evidence": evidence, "page": page}
    if len(distinct) > 1:
        evidence = " | ".join(candidate.evidence for candidate in candidates)
        return {"value": None, "confidence": 0.2, "evidence": evidence, "page": None}
    candidate = candidates[0]
    confidence = candidate.confidence
    # This version records reviewable confidence cues, not learned probabilities.
    if field == "issue_date" and re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", candidate.evidence):
        confidence = 0.72
    return {"value": candidate.value, "confidence": confidence, "evidence": candidate.evidence, "page": candidate.page}


def validate_result(result: dict[str, Any]) -> list[str]:
    """Return contract violations for an extraction result (empty means valid)."""
    errors: list[str] = []
    expected_top = {"schema_version", "source", "fields", "validation"}
    if set(result) != expected_top:
        errors.append("top-level keys do not match schema")
        return errors
    if result["schema_version"] != "1.0":
        errors.append("schema_version must be '1.0'")
    if not isinstance(result["source"], str):
        errors.append("source must be a string")
    validation = result["validation"]
    if (not isinstance(validation, dict) or set(validation) != {"valid", "errors"}
            or not isinstance(validation.get("valid"), bool)
            or not isinstance(validation.get("errors"), list)
            or any(not isinstance(error, str) for error in validation.get("errors", []))):
        errors.append("validation must contain a boolean valid flag and a string errors list")
    fields = result["fields"]
    if not isinstance(fields, dict) or set(fields) != set(FIELD_TYPES):
        errors.append("fields must contain exactly the declared field names")
        return errors
    for name, expected_type in FIELD_TYPES.items():
        entry = fields[name]
        if not isinstance(entry, dict) or set(entry) != {"value", "confidence", "evidence", "page"}:
            errors.append(f"{name} must contain value, confidence, evidence, and page")
            continue
        value, confidence, evidence, page = (entry[key] for key in ("value", "confidence", "evidence", "page"))
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            errors.append(f"{name}.confidence must be between 0 and 1")
        if evidence is not None and not isinstance(evidence, str):
            errors.append(f"{name}.evidence must be a string or null")
        if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
            errors.append(f"{name}.page must be a positive integer or null")
        if value is not None:
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"{name}.value must be a string or null")
            elif expected_type == "date":
                try:
                    if not isinstance(value, str) or datetime.strptime(value, "%Y-%m-%d").date().isoformat() != value:
                        raise ValueError
                except ValueError:
                    errors.append(f"{name}.value must be a valid ISO date or null")
            elif expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                errors.append(f"{name}.value must be a number or null")
            elif expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                errors.append(f"{name}.value must be an integer or null")
            if not isinstance(evidence, str) or page is None or not isinstance(confidence, (int, float)) or confidence == 0:
                errors.append(f"{name} needs evidence, a page, and nonzero confidence when value is present")
        elif evidence is None and confidence != 0:
            errors.append(f"{name} with no evidence must have confidence 0")
    return errors


def extract_text(text: str, source: str = "<text>", page_texts: list[str] | None = None) -> dict[str, Any]:
    """Extract known fields from text or page text; conflicts remain unresolved."""
    pages = page_texts if page_texts is not None else [text]
    candidates = _collect_candidates(pages)
    fields = {field: _field_result(field, candidates[field]) for field in ALIASES}
    result = {
        "schema_version": "1.0",
        "source": source,
        "fields": fields,
        "validation": {"valid": True, "errors": []},
    }
    errors = validate_result(result)
    result["validation"] = {"valid": not errors, "errors": errors}
    return result
