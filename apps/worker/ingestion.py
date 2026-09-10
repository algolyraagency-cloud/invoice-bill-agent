"""
Python Ingestion Module for RateGuard AI.
Handles Postmark webhook decoding, attachment extraction, ZIP unpacking, and CSV manifest parsing.
"""
import base64
import csv
import hashlib
import io
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple


def extract_slug_and_stream(email_address: str) -> Tuple[Optional[str], bool]:
    """
    Extracts customer slug and stream type from an email address.
    e.g.:
      - acme-parts@in.rateguard.app -> ('acme-parts', False)
      - disputes+acme-parts@in.rateguard.app -> ('acme-parts', True)
    """
    if not email_address:
        return None, False

    # Check if address targets RateGuard domain
    rg_match = re.search(r"([a-zA-Z0-9_\-\+]+)@(?:[a-zA-Z0-9_\-]+\.)?rateguard\.(?:app|ai)", email_address, re.IGNORECASE)
    if rg_match:
        local_part = rg_match.group(1).lower()
        if local_part.startswith("disputes+"):
            return local_part.replace("disputes+", ""), True
        return local_part, False

    match = re.search(r"([a-zA-Z0-9_\-\+]+)@", email_address)
    if not match:
        return None, False

    local_part = match.group(1).lower()
    if local_part.startswith("disputes+"):
        return local_part.replace("disputes+", ""), True

    return local_part, False


def compute_sha256(data: bytes) -> str:
    """Returns SHA256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def is_pdf_magic_bytes(data: bytes) -> bool:
    """Verifies that bytes start with %PDF- header."""
    return len(data) >= 5 and data[:5] == b"%PDF-"


def parse_postmark_inbound_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses a Postmark inbound JSON webhook dictionary.
    Extracts customer slug, recipient type, email metadata, and decodes attachments.
    """
    recipients: List[str] = []
    if payload.get("To"):
        recipients.append(str(payload["To"]))
    for r in payload.get("ToFull", []):
        if isinstance(r, dict) and r.get("Email"):
            recipients.append(str(r["Email"]))
    if payload.get("Cc"):
        recipients.append(str(payload["Cc"]))
    for r in payload.get("CcFull", []):
        if isinstance(r, dict) and r.get("Email"):
            recipients.append(str(r["Email"]))

    resolved_slug: Optional[str] = None
    is_dispute = False

    # Prioritize RateGuard recipient addresses first
    for rec in recipients:
        if "rateguard" in rec.lower():
            slug, dispute = extract_slug_and_stream(rec)
            if slug:
                resolved_slug = slug
                is_dispute = dispute
                break

    if not resolved_slug:
        for rec in recipients:
            slug, dispute = extract_slug_and_stream(rec)
            if slug:
                resolved_slug = slug
                is_dispute = dispute
                break

    # Parse and decode PDF attachments
    attachments = payload.get("Attachments", [])
    extracted_pdfs: List[Dict[str, Any]] = []

    for att in attachments:
        name = att.get("Name", "invoice.pdf")
        content_type = att.get("ContentType", "")
        content_b64 = att.get("Content", "")

        if content_type == "application/pdf" or name.lower().endswith(".pdf"):
            try:
                pdf_bytes = base64.b64decode(content_b64)
                if is_pdf_magic_bytes(pdf_bytes):
                    extracted_pdfs.append({
                        "filename": name,
                        "content_bytes": pdf_bytes,
                        "sha256": compute_sha256(pdf_bytes),
                        "size_bytes": len(pdf_bytes)
                    })
            except Exception:
                continue

    return {
        "slug": resolved_slug,
        "is_dispute_stream": is_dispute,
        "from_address": payload.get("From", ""),
        "subject": payload.get("Subject", ""),
        "date": payload.get("Date", ""),
        "body_text": payload.get("TextBody", ""),
        "body_html": payload.get("HtmlBody", ""),
        "pdf_attachments": extracted_pdfs
    }


def parse_csv_manifest(csv_text: str) -> Dict[str, Dict[str, Any]]:
    """
    Parses CSV manifest text mapping filename -> invoice metadata.
    """
    manifest: Dict[str, Dict[str, Any]] = {}
    f = io.StringIO(csv_text.strip())
    reader = csv.reader(f)
    try:
        headers = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return manifest

    # Resolve column indexes
    file_col = next((i for i, h in enumerate(headers) if "file" in h or "name" in h), -1)
    if file_col == -1:
        return manifest

    carrier_col = next((i for i, h in enumerate(headers) if "carrier" in h), -1)
    inv_col = next((i for i, h in enumerate(headers) if "invoice" in h and ("#" in h or "num" in h)), -1)
    pro_col = next((i for i, h in enumerate(headers) if "pro" in h), -1)
    total_col = next((i for i, h in enumerate(headers) if "total" in h or "amount" in h), -1)
    date_col = next((i for i, h in enumerate(headers) if "date" in h), -1)

    for row in reader:
        if len(row) <= file_col:
            continue
        fname = row[file_col].strip()
        if not fname:
            continue

        meta: Dict[str, Any] = {"file_name": fname}
        if carrier_col != -1 and len(row) > carrier_col:
            meta["carrier"] = row[carrier_col].strip()
        if inv_col != -1 and len(row) > inv_col:
            meta["invoice_number"] = row[inv_col].strip()
        if pro_col != -1 and len(row) > pro_col:
            meta["pro_number"] = row[pro_col].strip()
        if total_col != -1 and len(row) > total_col:
            try:
                meta["invoice_total"] = float(row[total_col].replace("$", "").replace(",", "").strip())
            except ValueError:
                meta["invoice_total"] = 0.0
        if date_col != -1 and len(row) > date_col:
            meta["invoice_date"] = row[date_col].strip()

        manifest[fname.lower()] = meta

    return manifest


def unpack_zip_invoices(zip_bytes: bytes) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Safely unpacks a ZIP archive in memory with zip-slip protection.
    Returns: (list_of_pdf_files, optional_csv_manifest_text)
    """
    extracted_pdfs: List[Dict[str, Any]] = []
    manifest_csv: Optional[str] = None

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            # Zip slip protection: skip paths with traversal
            if ".." in info.filename or info.filename.startswith("/"):
                continue

            # Skip directories and files over 25MB
            if info.is_dir() or info.file_size > 25 * 1024 * 1024:
                continue

            content = z.read(info.filename)
            base_name = os.path.basename(info.filename)

            # Check for CSV manifest
            if base_name.lower().endswith(".csv") and manifest_csv is None:
                try:
                    manifest_csv = content.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                continue

            # Check for PDF
            if is_pdf_magic_bytes(content):
                extracted_pdfs.append({
                    "filename": base_name,
                    "content_bytes": content,
                    "sha256": compute_sha256(content),
                    "size_bytes": len(content)
                })

    return extracted_pdfs, manifest_csv
