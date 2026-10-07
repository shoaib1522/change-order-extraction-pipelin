from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .extractor import extract_text


def _read_pdf_pages(reader: Any, source_name: str) -> list[str]:
    pages = [(page.extract_text() or "") for page in reader.pages]
    if not any(page.strip() for page in pages):
        raise RuntimeError(f"PDF '{source_name}' contains no extractable text; scanned PDFs require OCR.")
    return pages


def _read_input(path: Path) -> tuple[str, list[str] | None]:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace"), None
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as exc:
        raise RuntimeError("PDF support needs pypdf. Install with: pip install -e .") from exc
    try:
        reader = PdfReader(str(path))
        pages = _read_pdf_pages(reader, path.name)
    except PyPdfError as exc:
        raise RuntimeError(f"Could not read PDF '{path.name}': {exc}") from exc
    return "\n".join(pages), pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract evidence-backed fields from a change order PDF or text file.")
    parser.add_argument("input", type=Path, help="Path to a PDF or UTF-8 text file")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON here (defaults to stdout)")
    args = parser.parse_args()
    try:
        text, pages = _read_input(args.input)
        result = extract_text(text, source=args.input.name, page_texts=pages)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
