---
name: weread-optimizer
description: Use when the user asks for “微信读书优化流程”, wants HTML/PDF/TXT/images converted for WeChat Reading/微信读书, or needs EPUBs that preserve body text, heading hierarchy, inline images, and readable layout while removing web/PDF noise. Also use for optional quality triage of processed books.
metadata:
  short-description: Convert folders into WeRead-friendly EPUBs
---

# 微信读书优化流程

## Scope

Process a project folder into a separate output folder for 微信读书:

- primary output: WeRead-friendly EPUB
- supported public script inputs: `.html`, `.htm`, `.pdf`, `.txt`, `.png`, `.jpg`, `.jpeg`, `.webp`
- preserve body text, headings, paragraphs, lists, quotes, code blocks, tables, comparison grids, and body images where extractable
- keep body images near their original positions; do not dump images at the end
- remove obvious page/web noise such as navigation, sidebars, comments, buttons, ads, logos, and decorative page furniture
- detect video/audio/iframe/mp4 rich media and never silently omit it

Run the bundled script with `workdir` set to the user’s source folder:

```powershell
python -X utf8 scripts/weread_optimize.py
```

The script processes the current directory unless `WEREAD_INPUT_DIR` is set.

## HTML Collection Mode

Use this when the user wants one combined book from multiple HTML files:

```powershell
$env:WEREAD_HTML_ONLY='1'
$env:WEREAD_COMBINE_HTML='1'
$env:WEREAD_COLLECTION_TITLE='合集标题'
python -X utf8 scripts/weread_optimize.py
```

The script sorts numbered files by leading number, creates one EPUB, and inserts a visible chapter title at the start of every chapter body.

## Full-image PDF Export

Use this when the user asks for a PDF version of a generated EPUB, especially when they explicitly want images preserved.

Do not use direct PyMuPDF `convert_to_pdf()` on EPUB as the final answer for image-heavy books. It can keep text but replace body images with `[image]` placeholders. For full-fidelity PDFs:

1. Start from the full-image EPUB, not an audio-first/no-image EPUB.
2. Generate a printable HTML bundle:

```powershell
python -X utf8 scripts/epub_to_pdf_html.py <book.epub> --work-dir <work-dir> --html <work-dir>\combined-print.html
```

3. Split the printable HTML into front matter plus one HTML file per chapter:

```powershell
python -X utf8 scripts/split_pdf_html.py <work-dir>\combined-print.html --out-dir <work-dir>\split-html
```

4. Render each split HTML file to PDF with a real browser print engine. Use Chromium/Chrome through Playwright or the available browser automation. Wait for `document.fonts.ready` and for every `document.images` entry to load before printing. Keep print CSS that wraps code blocks:

```css
pre, code { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }
pre { overflow: visible; max-height: none; break-inside: auto; }
img { max-width: 100%; height: auto; object-fit: contain; }
```

5. Merge the split PDFs and produce a validation report:

```powershell
python -X utf8 scripts/merge_pdf_parts.py <work-dir>\split-pdf --output <output.pdf>
```

6. Validate before reporting success:
   - all expected chapter PDFs were merged
   - page count is non-zero and reasonable for the source
   - image references are present; an image-heavy source should not produce a tiny text-only PDF
   - all chapter titles can be found in extracted PDF text
   - representative code/pre blocks from the source HTML can be found in the PDF text
   - user-sensitive text such as table labels, headings, and code snippets is searchable

If browser rendering an entire book hangs, split by chapter before printing. Never silently switch to an image-only PDF for text/table/code content unless the user explicitly approves it, because voice playback and search will suffer.

## Required First Steps

1. Count source files and extensions in the current folder.
2. If the user says there should be N numbered files, parse leading numbers and report missing/duplicate/unparseable numbers before finalizing.
3. Check runtime availability and install missing packages if needed:
   - `pymupdf` for PDF
   - `Pillow` for image metadata
   - `beautifulsoup4` for HTML cleanup
4. If source files are DOCX/MOBI/PPT, convert them to HTML or PDF first, then run this skill.

## Validation Checklist

After conversion:

1. Confirm EPUB count vs manifest count.
2. Confirm failures are zero, or list failed files with reasons.
3. Spot-check EPUB zip entries and image references when images are extracted.
4. Confirm `处理报告.md` includes source count, missing/duplicate numbered files, rich-media handling, scan/image-page handling, and output list.
5. Provide links to the output folder, EPUB folder, and report.

## Interaction/Rich Media Rule

If video/audio/iframe/mp4 is found:

- state that 微信读书 EPUB cannot fully preserve those interactive components
- state how they were handled: static text/images retained; interaction not embedded; note inserted in the corresponding EPUB
- do not imply full fidelity

## Scan/OCR Limitation Rule

If PDF pages have no text layer or the source is an image:

- preserve them as page images so they can be viewed and enlarged
- mark them as scan/image pages in `处理报告.md`
- clearly state that 微信读书 voice playback cannot fully read those pages
- do not claim complete text extraction unless OCR was actually run

## Final Response Pattern

Keep final concise:

- what was produced
- counts
- any failed/limited files
- links to output artifacts

Do not ask the user to re-upload if the current folder or file library already contains the same files; continue from local files whenever possible.
