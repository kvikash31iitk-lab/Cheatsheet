import os
import sys
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz
from scripts.build_structured_notes import build, parse_formula_components, clean_latex_math

def test_parse_formula_components():
    # Test 1: Standard ratio
    label, num, den, mult = parse_formula_components("Current Ratio = Current Assets / Current Liabilities")
    assert "Current Ratio" in label
    assert num == "Current Assets"
    assert den == "Current Liabilities"
    assert mult == ""

    # Test 2: Label prefix with LaTeX fraction
    label, num, den, mult = parse_formula_components("1. Quantity-Based: \\frac{Total Expense}{Total Units Produced}")
    assert "1. Quantity-Based:" in label
    assert num == "Total Expense"
    assert den == "Total Units Produced"

    # Test 3: Multiplier and evaluation
    label, num, den, mult = parse_formula_components("Fixed Cost/Unit = \\frac{Total Fixed Cost}{Total Units} = 220,000/12,000 ≈ Rs. 18.33")
    assert "Fixed Cost/Unit" in label
    assert num == "Total Fixed Cost"
    assert "Total Units" in den
    assert "Rs. 18.33" in mult

def test_pdf_rendering_no_diagonal_line(tmp_path):
    md_content = """# Test Document

## I. Section 1
Here is a normal paragraph.

---

### Sub topic 1
1. Quantity-Based: \\frac{Total Expense}{Total Units Produced}

| Header 1 | Header 2 | Header 3 |
| --- | --- | --- |
| Row 1 | Data 1 | Detail 1 |
| Row 2 | Data 2 | Detail 2 |
| Row 3 | Data 3 | Detail 3 |
"""
    md_file = tmp_path / "test.md"
    pdf_file = tmp_path / "test.pdf"
    md_file.write_text(md_content, encoding="utf-8")

    build(md_file, pdf_file, title="Test Verification Document")

    assert pdf_file.exists()
    doc = fitz.open(pdf_file)
    assert len(doc) >= 1

    # Verify no raw '---' in PDF text
    page_text = doc[0].get_text()
    assert "---" not in page_text

if __name__ == "__main__":
    import tempfile
    print("Testing parse_formula_components...")
    test_parse_formula_components()
    print("Formula parser OK!")
    print("Testing PDF rendering...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_pdf_rendering_no_diagonal_line(pathlib.Path(tmp_dir))
    print("PDF rendering OK!")
    print("ALL TESTS PASSED SUCCESSFULLY!")
