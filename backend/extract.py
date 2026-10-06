import subprocess
import sys
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

OCR_SCRIPT = Path(__file__).with_name("ocr_cli.py")


def run_ocr(path: str) -> str:
    """Run OCR in a separate process, so its memory goes back to the system when it ends."""
    result = subprocess.run(
        [sys.executable, str(OCR_SCRIPT), path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        raise RuntimeError(lines[-1][:300] if lines else "OCR process failed")
    return result.stdout


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        # Almost no text found: the PDF is probably a scan (pictures of text)
        if len(text.strip()) < 30 * len(reader.pages):
            ocr_error = None
            try:
                ocr_text = run_ocr(path)
                if len(ocr_text.strip()) > len(text.strip()):
                    return ocr_text
            except Exception as e:
                ocr_error = f"{type(e).__name__}: {e}"
                print("OCR failed:", ocr_error)

            if not text.strip() and ocr_error:
                raise RuntimeError(f"OCR failed: {ocr_error}")
        return text

    if ext == ".docx":
        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs)

    # .txt, .md, .csv are plain text
    return Path(path).read_text(encoding="utf-8", errors="ignore")