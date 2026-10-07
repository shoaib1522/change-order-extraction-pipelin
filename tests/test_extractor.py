from __future__ import annotations

import json
import io
import sys
import unittest
from io import BytesIO
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent / "src"))

from change_order_extractor.cli import _read_input, _read_pdf_pages, main
from change_order_extractor.extractor import extract_text, validate_result


class ExtractorTests(unittest.TestCase):
    def test_schema_file_is_valid_json_and_matches_fields(self) -> None:
        schema = json.loads((ROOT.parent / "schema.json").read_text(encoding="utf-8"))
        declared = set(schema["properties"]["fields"]["required"])
        result = extract_text("")
        self.assertEqual(set(result["fields"]), declared)

    def test_labeled_change_order_and_json_contract(self) -> None:
        source = (ROOT / "fixtures" / "change_order.txt").read_text(encoding="utf-8")
        result = extract_text(source, source="change_order.txt")
        self.assertTrue(result["validation"]["valid"], result["validation"]["errors"])
        self.assertEqual([], validate_result(result))
        self.assertEqual("CO-017", result["fields"]["change_order_number"]["value"])
        self.assertEqual("2025-04-04", result["fields"]["issue_date"]["value"])
        self.assertEqual(12450.5, result["fields"]["cost_change"]["value"])
        self.assertEqual(3, result["fields"]["schedule_impact_days"]["value"])
        self.assertIn("inspection", result["fields"]["description"]["value"])
        self.assertEqual(1, result["fields"]["description"]["page"])
        self.assertEqual("Net Change: $12,450.50", result["fields"]["cost_change"]["evidence"])
        json.loads(json.dumps(result))

    def test_ambiguous_date_is_retained_as_unresolved_evidence(self) -> None:
        result = extract_text("Issue Date: 03/04/2025")
        field = result["fields"]["issue_date"]
        self.assertIsNone(field["value"])
        self.assertEqual("Issue Date: 03/04/2025", field["evidence"])
        self.assertLess(field["confidence"], 0.5)

    def test_conflicting_values_are_not_silently_chosen(self) -> None:
        result = extract_text("Status: Approved\nStatus: Pending")
        field = result["fields"]["status"]
        self.assertIsNone(field["value"])
        self.assertIn("Approved", field["evidence"])
        self.assertIn("Pending", field["evidence"])
        self.assertLess(field["confidence"], 0.5)

    def test_negative_amount_formats(self) -> None:
        for text, expected in (("Net Change: ($1,200.00)", -1200),
                               ("Net Change: 1,200.50 CR", -1200.5),
                               ("Net Change: USD 1,200", 1200)):
            with self.subTest(text=text):
                self.assertEqual(expected, extract_text(text)["fields"]["cost_change"]["value"])

    def test_malformed_money_is_unresolved(self) -> None:
        field = extract_text("Net Change: $12,45.789")["fields"]["cost_change"]
        self.assertIsNone(field["value"])
        self.assertEqual("Net Change: $12,45.789", field["evidence"])

    def test_schedule_units_are_normalized_without_guessing(self) -> None:
        fields = extract_text("Schedule Impact: 2 weeks | Status: Pending")["fields"]
        self.assertEqual(14, fields["schedule_impact_days"]["value"])
        self.assertEqual(0, extract_text("Schedule Impact: No impact")["fields"]["schedule_impact_days"]["value"])
        self.assertIsNone(extract_text("Schedule Impact: about 2")["fields"]["schedule_impact_days"]["value"])
        self.assertIsNone(extract_text("Schedule Impact: 2 weeks or 10 days")["fields"]["schedule_impact_days"]["value"])

    def test_pipe_cells_and_next_line_values(self) -> None:
        text = "\n".join((
            "Project Name: Tower A | Owner: City Works",
            "Change Order No:",
            "CO-204",
            "Approved By:",
            "A. Morgan",
        ))
        fields = extract_text(text)["fields"]
        self.assertEqual("Tower A", fields["project_name"]["value"])
        self.assertEqual("City Works", fields["owner"]["value"])
        self.assertEqual("CO-204", fields["change_order_number"]["value"])
        self.assertEqual("A. Morgan", fields["approved_by"]["value"])
        self.assertEqual(0.95, fields["project_name"]["confidence"])
        self.assertEqual(0.85, fields["change_order_number"]["confidence"])

    def test_page_provenance_is_preserved(self) -> None:
        result = extract_text("", page_texts=["Project: First", "Project: Second"])
        field = result["fields"]["project_name"]
        self.assertIsNone(field["value"])
        self.assertIsNone(field["page"])
        self.assertIn("First", field["evidence"])
        self.assertIn("Second", field["evidence"])

    def test_validator_detects_contract_tampering(self) -> None:
        result = extract_text("Status: Approved")
        result["fields"]["status"]["confidence"] = 1.5
        self.assertTrue(any("confidence" in error for error in validate_result(result)))

    def test_pdf_cli_reads_real_pdf_file_end_to_end(self) -> None:
        pdf_path = ROOT / "fixtures" / "change_order.pdf"
        output = io.StringIO()
        with patch("sys.argv", ["change-order-extract", str(pdf_path)]), redirect_stdout(output):
            self.assertEqual(0, main())
        result = json.loads(output.getvalue())
        self.assertEqual("Tower A", result["fields"]["project_name"]["value"])
        self.assertEqual("Approved", result["fields"]["status"]["value"])
        self.assertEqual(14, result["fields"]["schedule_impact_days"]["value"])
        self.assertEqual(1, result["fields"]["project_name"]["page"])
        self.assertTrue(result["validation"]["valid"], result["validation"]["errors"])

    def test_malformed_pdf_returns_actionable_error(self) -> None:
        pdf_path = ROOT / "fixtures" / "corrupt.pdf"
        with self.assertRaisesRegex(RuntimeError, "Could not read PDF 'corrupt.pdf'"):
            _read_input(pdf_path)

    def test_blank_pdf_is_reported_as_needing_ocr(self) -> None:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        pdf_data = BytesIO()
        writer.write(pdf_data)
        pdf_data.seek(0)
        reader = PdfReader(pdf_data)
        with self.assertRaisesRegex(RuntimeError, "contains no extractable text"):
            _read_pdf_pages(reader, "scanned.pdf")

    def test_cli_writes_parseable_json_for_text_input(self) -> None:
        input_path = ROOT / "fixtures" / "change_order.txt"
        output = io.StringIO()
        with patch("sys.argv", ["change-order-extract", str(input_path)]), redirect_stdout(output):
            self.assertEqual(0, main())
        result = json.loads(output.getvalue())
        self.assertEqual("Approved", result["fields"]["status"]["value"])


if __name__ == "__main__":
    unittest.main()
