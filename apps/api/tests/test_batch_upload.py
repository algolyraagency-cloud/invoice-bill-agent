"""
Tests for Batch Upload, ZIP Unpacking, and CSV Manifest Parsing (Phase 1.2).
"""
import io
import zipfile

from apps.worker.ingestion import is_pdf_magic_bytes, parse_csv_manifest, unpack_zip_invoices


def create_synthetic_zip(num_pdfs: int = 5, include_csv: bool = True) -> bytes:
    """Generates an in-memory ZIP archive containing synthetic PDFs and a manifest CSV."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        # Add synthetic PDFs
        sample_pdf = b"%PDF-1.4\nsynthetic invoice payload\n%%EOF"
        for i in range(1, num_pdfs + 1):
            filename = f"invoices/inv_{i:04d}.pdf"
            z.writestr(filename, sample_pdf)

        # Add malicious path traversal attempt (zip slip) to verify security
        z.writestr("../evil_file.pdf", b"%PDF-1.4\nevil payload\n%%EOF")

        # Add a non-PDF to verify filter
        z.writestr("notes.txt", b"just a text note")

        # Add CSV manifest
        if include_csv:
            csv_content = "file_name,carrier,invoice_number,pro_number,invoice_total,invoice_date\n"
            for i in range(1, num_pdfs + 1):
                csv_content += f"inv_{i:04d}.pdf,ABF Freight,INV-{i:04d},PRO-{i:04d},150.50,2026-08-10\n"
            z.writestr("manifest.csv", csv_content)

    return zip_buffer.getvalue()


def test_unpack_zip_invoices_safe():
    zip_bytes = create_synthetic_zip(num_pdfs=5, include_csv=True)
    pdfs, manifest_csv = unpack_zip_invoices(zip_bytes)

    # 5 valid PDFs (evil_file.pdf and notes.txt must be safely excluded)
    assert len(pdfs) == 5
    for pdf in pdfs:
        assert pdf["filename"].startswith("inv_")
        assert is_pdf_magic_bytes(pdf["content_bytes"]) is True

    assert manifest_csv is not None
    assert "inv_0001.pdf" in manifest_csv


def test_parse_csv_manifest():
    csv_text = """
    file_name,carrier,invoice_number,pro_number,invoice_total,invoice_date
    inv_0001.pdf,ABF Freight,INV-101,042-998811,$340.50,2026-08-15
    inv_0002.pdf,XPO Logistics,INV-102,XPO-554433,1250.00,2026-08-16
    """
    manifest = parse_csv_manifest(csv_text)
    assert len(manifest) == 2
    assert "inv_0001.pdf" in manifest

    item1 = manifest["inv_0001.pdf"]
    assert item1["carrier"] == "ABF Freight"
    assert item1["invoice_number"] == "INV-101"
    assert item1["pro_number"] == "042-998811"
    assert item1["invoice_total"] == 340.50
    assert item1["invoice_date"] == "2026-08-15"


def test_batch_scale_unpacking():
    # Test batch unpacking with 100 files to verify memory and speed
    zip_bytes = create_synthetic_zip(num_pdfs=100, include_csv=True)
    pdfs, manifest_csv = unpack_zip_invoices(zip_bytes)
    assert len(pdfs) == 100
    assert manifest_csv is not None
