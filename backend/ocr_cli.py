import sys

from ocr import ocr_pdf

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(ocr_pdf(sys.argv[1]))