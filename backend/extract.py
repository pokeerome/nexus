from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        # Almost no text found: the PDF is probably a scan (pictures of text)
        if len(text.strip()) < 30 * len(reader.pages):
            try:
                from ocr import ocr_pdf

                ocr_text = ocr_pdf(path)
                if len(ocr_text.strip()) > len(text.strip()):
                    return ocr_text
            except Exception as e:
                print("OCR failed:", e)
        return text

    if ext == ".docx":
        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs)

    # .txt, .md, .csv are plain text
    return Path(path).read_text(encoding="utf-8", errors="ignore")