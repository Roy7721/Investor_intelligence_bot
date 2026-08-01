import pymupdf4llm

# convert the WHOLE document, not a page slice
md_text = pymupdf4llm.to_markdown("./data/raw_pdfs/2024_Apple.pdf")

with open("apple_full.md", "w",encoding="utf-8") as f:
    f.write(md_text)

# now search for something you know is unique and near the income statement
# e.g. a distinctive phrase from the table you screenshotted
idx = md_text.find("CONSOLIDATED STATEMENTS OF OPERATIONS")
print(idx)
print(md_text[idx:idx+2000])