import json
from pathlib import Path

chunks = json.loads(Path("data/cache/Apple_2024_b9dc49ea295eea1d_v5.json").read_text(encoding="utf-8"))

for i, c in enumerate(chunks):
    if c.get("conversion_status") == "raw_fallback":
        print(f"--- chunk {i} ---")
        print(c["text"][:400])
        print()