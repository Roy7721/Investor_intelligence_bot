from pathlib import Path

import pymupdf4llm

def convert_pdf(input_path: str, output_path : str) -> str:
    """This function converts the pdf into markdown file in a 
    systematic way"""

    pdf_file_address = Path(input_path)

    if not pdf_file_address.exists():
        raise FileNotFoundError(f"The pdf doesnot exists in the given directory.Please Recheck again!")

    output_file_address = Path(output_path)

    output_file_address.mkdir(exist_ok=True, parents=True)

    md_text = pymupdf4llm.to_markdown(str(pdf_file_address))

    md_file = output_file_address / f"{pdf_file_address.stem}.md"

    md_file.write_text(
        data=md_text,
        encoding="utf-8"
    )

    return str(md_file)


def convert_directory(input_dir: str, output_dir : str) -> list[str]:
    """This function takes the path of all pdf and put them in
    convert_pdf one by one and save markdown is list"""

    input_dir= Path(input_dir)
    output_dir = Path(output_dir)

    markdown_filess = []

    for pdf_path_address in input_dir.glob("*.pdf"):
        markdown_file = convert_pdf(input_path=pdf_path_address, output_path=output_dir)

        markdown_filess.append(markdown_file)

    return markdown_filess

if __name__ == "__main__":
    repo_path = Path(__file__).resolve().parents[1]
    input_dir = repo_path / "data" / "raw_pdfs"
    output_dir = repo_path / "data" / "markdown"

    markdown_filess=convert_directory(input_dir=input_dir,output_dir=output_dir)

    if markdown_filess :
        print("All file converted succesfully!")

    for markdown_file in markdown_filess:
        print(f" - {markdown_file}")




