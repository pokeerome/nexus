import io
import os
import shutil

import pymupdf
import pytesseract
from PIL import Image

WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.name == "nt" and not shutil.which("tesseract") and os.path.exists(WINDOWS_TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = WINDOWS_TESSERACT


def ocr_pdf(path: str, max_pages: int = 10, dpi: int = 150) -> str:
    pages = []
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            pages.append(pytesseract.image_to_string(image))
    return "\n".join(pages)