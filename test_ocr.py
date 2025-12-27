import ddddocr
import sys

print("Testing ddddocr...")
try:
    ocr = ddddocr.DdddOcr(show_ad=False)
    print("ddddocr initialized successfully")
except Exception as e:
    print(f"Error initializing ddddocr: {e}")
    sys.exit(1)
