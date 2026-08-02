import json
from pathlib import Path

chunks = json.loads(Path("data/cache/Tesla_2024_9b08571158ef66bc_v5.json").read_text(encoding="utf-8"))

for i, c in enumerate(chunks):
    if c.get("conversion_status") == "raw_fallback":
        print(f"--- chunk {i} ---")
        print(c["text"][:400])
        print()