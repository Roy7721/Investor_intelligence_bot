from pathlib import Path 
markdown_file = Path("./apple_full.md")

content = markdown_file.read_text(encoding = "utf-8")

import re

blocks = re.split(r"\n{2,}", content) 

prose_block = []
table_block = []

for block in blocks:
    print(block) 

    

    lines = block.strip().split("\n")
    is_table = any(line.strip().startswith("|") or line.strip().endswith("|") for line in lines)

    block = re.sub("<br>", "",block)
    
    if is_table:
        
        table_block.append(block)

    else:
        prose_block.append(block)

prose_text = "\n\n".join(prose_block)
table_text = "\n\n".join(table_block)
    
print(table_block)