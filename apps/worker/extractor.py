"""
Document text & table extraction worker module.
Implements IBM Docling layout extraction with PyPDF fallback as codified in Phase 0.2 spike.
"""
import hashlib
from pathlib import Path
from typing import Tuple


def extract_document_text(file_path: str) -> Tuple[str, str, str]:
    """
    Extracts text/markdown from PDF file.
    Returns: (extracted_content, method_used, content_sha256)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found at {file_path}")

    # Read raw bytes for hash
    with open(path, "rb") as f:
        content_bytes = f.read()
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # 1. Primary Engine: Docling (if installed)
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(file_path)
        markdown_text = result.document.export_to_markdown()
        return markdown_text, "docling", content_hash
    except Exception:
        pass

    # 2. Fast Fallback Engine: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages_text = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            pages_text.append(f"--- Page {i + 1} ---\n{page_text}")
        full_text = "\n\n".join(pages_text)
        return full_text, "pypdf_fallback", content_hash
    except Exception as pypdf_err:
        raise RuntimeError(f"All PDF extraction engines failed for {file_path}: {pypdf_err}")
