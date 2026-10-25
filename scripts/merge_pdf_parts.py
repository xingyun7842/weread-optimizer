from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz


def natural_part_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    if stem == "part-00-front":
        return (0, stem)
    pieces = stem.split("-")
    for piece in reversed(pieces):
        if piece.isdigit():
            return (int(piece), stem)
    return (9999, stem)


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge chapter PDF parts and report page/image counts.")
    parser.add_argument("parts_dir", type=Path, help="Directory containing part-*.pdf files.")
    parser.add_argument("--output", type=Path, required=True, help="Merged PDF output path.")
    parser.add_argument("--expected-parts", type=int, default=13, help="Expected PDF part count.")
    parser.add_argument("--allow-missing", action="store_true", help="Do not fail when the part count is unexpected.")
    args = parser.parse_args()

    parts = sorted(args.parts_dir.glob("part-*.pdf"), key=natural_part_key)
    if not parts:
        raise SystemExit(f"No part PDFs found in {args.parts_dir}")
    if len(parts) != args.expected_parts and not args.allow_missing:
        raise SystemExit(f"Expected {args.expected_parts} part PDFs, found {len(parts)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()

    merged = fitz.open()
    report_parts: list[dict[str, int | str]] = []
    for part in parts:
        src = fitz.open(part)
        image_refs = sum(len(page.get_images(full=True)) for page in src)
        report_parts.append(
            {
                "name": part.name,
                "pages": src.page_count,
                "size_bytes": part.stat().st_size,
                "image_refs": image_refs,
            }
        )
        merged.insert_pdf(src)
        src.close()

    merged.save(args.output, garbage=4, deflate=True, deflate_images=False, deflate_fonts=True)
    total_pages = merged.page_count
    merged.close()

    report = {
        "output": str(args.output),
        "output_size_bytes": args.output.stat().st_size,
        "part_count": len(parts),
        "total_pages": total_pages,
        "total_image_refs": sum(int(part["image_refs"]) for part in report_parts),
        "parts": report_parts,
    }
    report_path = args.output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
