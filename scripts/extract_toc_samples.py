from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path


ROOT = Path.cwd().resolve()
OUT = ROOT / "微信读书优化输出"
EPUB_DIR = OUT / "epub"


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def extract_epub(epub: Path) -> dict:
    headings: list[str] = []
    samples: list[str] = []
    scan_notes = 0
    try:
        with zipfile.ZipFile(epub) as zf:
            names = [name for name in zf.namelist() if name.startswith("OEBPS/text/") and name.endswith(".xhtml")]
            for name in names[:20]:
                text = zf.read(name).decode("utf-8", "replace")
                scan_notes += text.count("[扫描页")
                for match in re.finditer(r"<h([1-3])[^>]*>(.*?)</h\1>", text, flags=re.S | re.I):
                    heading = strip_tags(match.group(2))
                    if heading and heading not in headings:
                        headings.append(heading[:160])
                    if len(headings) >= 50:
                        break
                for match in re.finditer(r"<p[^>]*>(.*?)</p>", text, flags=re.S | re.I):
                    sample = strip_tags(match.group(1))
                    if sample and not sample.startswith("[") and len(sample) > 20:
                        samples.append(sample[:260])
                    if len(samples) >= 8:
                        break
                if len(headings) >= 50 and len(samples) >= 8:
                    break
    except Exception as exc:
        headings.append(f"ERR {type(exc).__name__}: {exc}")
    return {
        "epub": epub.name,
        "headings": headings[:50],
        "samples": samples[:8],
        "scan_note_hits": scan_notes,
    }


def main() -> None:
    rows = [extract_epub(epub) for epub in sorted(EPUB_DIR.glob("*.epub"), key=lambda p: p.name)]
    path = OUT / "目录标题样本.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    print("rows", len(rows))
    for target in ["96、", "kk所有", "45、", "59、", "183、"]:
        for row in rows:
            if row["epub"].startswith(target):
                print("\n==", row["epub"])
                print("HEADINGS")
                for heading in row["headings"][:20]:
                    print("-", heading)
                print("SAMPLES")
                for sample in row["samples"][:4]:
                    print("-", sample)


if __name__ == "__main__":
    main()
