from __future__ import annotations

import argparse
import html
import re
import shutil
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup


def read_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8", "ignore")


def clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value or "Untitled"


def rewrite_asset_refs(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["img", "source"]):
        attr = "src"
        value = tag.get(attr)
        if value and value.startswith("../"):
            tag[attr] = value[3:]
    for tag in soup.find_all(["a"]):
        href = tag.get("href")
        if href and href.startswith("../"):
            tag["href"] = href[3:]


def body_inner(xhtml: str) -> tuple[str, str]:
    soup = BeautifulSoup(xhtml, "html.parser")
    title = clean_title((soup.title.get_text(" ", strip=True) if soup.title else ""))
    body = soup.body or soup
    rewrite_asset_refs(body)
    return title, "".join(str(child) for child in body.children)


def extract_nav_items(nav_html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(nav_html, "html.parser")
    items: list[tuple[str, str]] = []
    for link in soup.find_all("a"):
        href = link.get("href") or ""
        text = clean_title(link.get_text(" ", strip=True))
        if href and text:
            items.append((text, href))
    return items


def build_combined_html(epub_path: Path, work_dir: Path, output_html: Path) -> dict:
    extract_dir = work_dir / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(extract_dir)
        names = zf.namelist()
        chapter_names = sorted(
            [name for name in names if name.startswith("OEBPS/text/") and name.endswith(".xhtml")]
        )
        nav_items: list[tuple[str, str]] = []
        if "OEBPS/toc.xhtml" in names:
            nav_items = extract_nav_items(read_text(zf, "OEBPS/toc.xhtml"))

        css_parts = []
        if "OEBPS/styles.css" in names:
            css_parts.append(read_text(zf, "OEBPS/styles.css"))

        sections = []
        titles = []
        for index, name in enumerate(chapter_names, 1):
            title, inner = body_inner(read_text(zf, name))
            titles.append(title)
            sections.append(
                f'<section class="pdf-chapter" id="chapter-{index:02d}" data-source="{html.escape(name)}">\n'
                f"{inner}\n"
                "</section>"
            )

    toc_html = ""
    if nav_items:
        toc_entries = []
        for text, href in nav_items:
            rewritten = href.replace("text/", "#pdf-")
            rewritten = rewritten.replace(".xhtml", "")
            # part0001#anchor -> #pdf-part0001-anchor
            rewritten = rewritten.replace("#", "-")
            if not rewritten.startswith("#"):
                rewritten = "#" + rewritten
            toc_entries.append(f'<li><a href="{html.escape(rewritten, quote=True)}">{html.escape(text)}</a></li>')
        toc_html = '<nav class="pdf-toc"><h1>目录</h1><ol>' + "\n".join(toc_entries) + "</ol></nav>"

    # Give chapter and heading anchors predictable ids for generated PDF links.
    full_body = "\n".join(sections)
    soup = BeautifulSoup(full_body, "html.parser")
    for section_index, section in enumerate(soup.select("section.pdf-chapter"), 1):
        source = section.get("data-source", "")
        m = re.search(r"(part\d+)\.xhtml$", source)
        part_id = m.group(1) if m else f"part{section_index:04d}"
        section["id"] = f"pdf-{part_id}"
        for tag in section.find_all(id=True):
            if tag is section:
                continue
            tag["id"] = f"pdf-{part_id}-{tag['id']}"

    print_css = """
@page { size: A4; margin: 15mm 13mm; }
html, body { background: #fff; }
body {
  color: #111;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
  line-height: 1.72;
  margin: 0;
}
.pdf-cover {
  break-after: page;
  min-height: 92vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  text-align: center;
}
.pdf-cover h1 { font-size: 28pt; line-height: 1.35; margin: 0 0 16pt; }
.pdf-cover p { text-indent: 0; color: #555; font-size: 11pt; }
.pdf-toc { break-after: page; }
.pdf-toc h1 { text-align: center; }
.pdf-toc ol { padding-left: 1.4em; }
.pdf-toc li { margin: 0.18em 0; line-height: 1.45; }
.pdf-chapter { break-before: page; }
h1, h2, h3, h4 { break-after: avoid; page-break-after: avoid; }
p, li, blockquote { orphans: 2; widows: 2; }
pre, code {
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: break-word !important;
}
pre {
  overflow: visible !important;
  max-height: none !important;
  break-inside: auto;
  page-break-inside: auto;
}
img {
  max-width: 100% !important;
  height: auto !important;
  object-fit: contain;
  break-inside: avoid;
  page-break-inside: avoid;
}
table, .text-table, .callout, blockquote { break-inside: avoid; }
a { color: #1266a8; text-decoration: none; }
"""

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(epub_path.stem)}</title>
  <base href="{(extract_dir / 'OEBPS').as_uri()}/" />
  <style>{''.join(css_parts)}</style>
  <style>{print_css}</style>
</head>
<body>
  <section class="pdf-cover">
    <h1>{html.escape(epub_path.stem)}</h1>
    <p>由 EPUB 生成的带图 PDF，保留正文、代码、图片、目录、加粗、高亮和文本表格。</p>
  </section>
  {toc_html}
  {str(soup)}
</body>
</html>
"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html_doc, encoding="utf-8")
    return {
        "epub": str(epub_path),
        "html": str(output_html),
        "extract_dir": str(extract_dir),
        "chapters": len(chapter_names),
        "titles": titles,
        "toc_links": len(nav_items),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    args = parser.parse_args()
    result = build_combined_html(args.epub.resolve(), args.work_dir.resolve(), args.html.resolve())
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
