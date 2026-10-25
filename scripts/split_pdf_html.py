from __future__ import annotations

import argparse
import json
from pathlib import Path

from bs4 import BeautifulSoup


def build_html(title: str, head_bits: str, body_bits: list[str], *, chapter_chunk: bool) -> str:
    override = """
<style>
body.pdf-split-chunk { margin: 0; }
body.pdf-split-chunk .pdf-chapter { break-before: auto !important; page-break-before: auto !important; }
body.pdf-split-chunk pre,
body.pdf-split-chunk code {
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: break-word !important;
}
body.pdf-split-chunk pre {
  overflow: visible !important;
  max-height: none !important;
  break-inside: auto !important;
  page-break-inside: auto !important;
}
</style>
""".strip()
    body_class = ' class="pdf-split-chunk"' if chapter_chunk else ""
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8" />',
            f"  <title>{title}</title>",
            head_bits,
            override,
            "</head>",
            f"<body{body_class}>",
            *body_bits,
            "</body>",
            "</html>",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("combined_html", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    soup = BeautifulSoup(args.combined_html.read_text(encoding="utf-8"), "html.parser")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    base = soup.head.find("base")
    styles = soup.head.find_all("style")
    head_bits = "\n".join(str(tag) for tag in ([base] if base else []) + styles)
    doc_title = soup.title.get_text(strip=True) if soup.title else "EPUB PDF"

    parts: list[dict[str, object]] = []

    cover = soup.select_one("section.pdf-cover")
    toc = soup.select_one("nav.pdf-toc")
    front_nodes = [str(node) for node in [cover, toc] if node]
    if front_nodes:
        html_path = args.out_dir / "part-00-front.html"
        html_path.write_text(
            build_html(f"{doc_title} - 封面目录", head_bits, front_nodes, chapter_chunk=False),
            encoding="utf-8",
        )
        front_soup = BeautifulSoup("\n".join(front_nodes), "html.parser")
        parts.append(
            {
                "index": 0,
                "label": "封面目录",
                "html": str(html_path),
                "images": len(front_soup.find_all("img")),
                "pre": len(front_soup.find_all("pre")),
                "text_length": len(front_soup.get_text("", strip=True)),
            }
        )

    chapters = soup.select("section.pdf-chapter")
    for index, chapter in enumerate(chapters, start=1):
        heading = chapter.find(["h1", "h2", "h3"])
        label = heading.get_text(" ", strip=True) if heading else f"第 {index:02d} 节"
        html_path = args.out_dir / f"part-{index:02d}.html"
        chapter_html = str(chapter)
        html_path.write_text(
            build_html(f"{doc_title} - {label}", head_bits, [chapter_html], chapter_chunk=True),
            encoding="utf-8",
        )
        chapter_soup = BeautifulSoup(chapter_html, "html.parser")
        parts.append(
            {
                "index": index,
                "label": label,
                "html": str(html_path),
                "images": len(chapter_soup.find_all("img")),
                "pre": len(chapter_soup.find_all("pre")),
                "tables": len(chapter_soup.find_all("table")),
                "text_length": len(chapter_soup.get_text("", strip=True)),
            }
        )

    manifest_path = args.out_dir / "parts.json"
    manifest_path.write_text(json.dumps(parts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "parts": len(parts),
                "chapters": len(chapters),
                "images": sum(int(part.get("images", 0)) for part in parts),
                "pre": sum(int(part.get("pre", 0)) for part in parts),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
