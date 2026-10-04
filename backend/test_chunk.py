import sys

from chunker import chunk_text
from extract import extract_text

text = extract_text(sys.argv[1])
chunks = chunk_text(text)

print("characters:", len(text))
print("chunks:", len(chunks))
print("--- first chunk ---")
print(chunks[0][:300])