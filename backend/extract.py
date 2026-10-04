from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if ext == ".docx":
        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs)

    # .txt, .md, .csv are plain text
    return Path(path).read_text(encoding="utf-8", errors="ignore")