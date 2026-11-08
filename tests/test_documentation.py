import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = sorted([*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"), *(ROOT / ".github").rglob("*.md")])


def test_local_links_and_images_in_markdown_exist():
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)  # ignore code blocks
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            path = (document.parent / target.split("#", 1)[0]).resolve()
            assert path.exists(), f"{document.relative_to(ROOT)} links to missing {target}"
