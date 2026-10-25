# weread-optimizer

Codex skill for converting course/book folders into WeRead-friendly EPUB files.

## What It Does

- Converts HTML, PDF, TXT, and image files into EPUB.
- Combines ordered HTML files into one EPUB collection for WeRead.
- Optimizes HTML exports by extracting readable content blocks instead of dumping full webpages.
- Preserves headings, paragraphs, lists, code blocks, links, tables, comparison grids, blockquotes, and body images where extractable.
- Converts div-based pseudo tables and comparison grids into EPUB-friendly tables.
- Keeps notes for video/audio/iframe content because EPUB cannot embed those interactions reliably.

## Install

Clone or download this repository into your Codex skills directory.

### Windows PowerShell

```powershell
iwr https://raw.githubusercontent.com/xingyun7842/weread-optimizer/main/install.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Manual install:

```powershell
$SkillDir = "$env:USERPROFILE\.codex\skills\weread-optimizer"
New-Item -ItemType Directory -Force -Path (Split-Path $SkillDir) | Out-Null
git clone https://github.com/xingyun7842/weread-optimizer.git $SkillDir
python -m pip install -r "$SkillDir\requirements.txt"
```

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/xingyun7842/weread-optimizer/main/install.sh | bash
```

Manual install:

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/xingyun7842/weread-optimizer.git "$HOME/.codex/skills/weread-optimizer"
python3 -m pip install -r "$HOME/.codex/skills/weread-optimizer/requirements.txt"
```

## Usage

Ask Codex to use the skill on a folder:

```text
[$weread-optimizer](~/.codex/skills/weread-optimizer/SKILL.md) Process this folder for WeRead EPUB output.
```

The core script processes the current directory by default:

```bash
python -X utf8 scripts/weread_optimize.py
```

Useful environment variables:

- `WEREAD_INPUT_DIR`: source folder to process.
- `WEREAD_OUTPUT_DIR`: output folder.
- `WEREAD_HTML_ONLY=1`: process only HTML files.
- `WEREAD_COMBINE_HTML=1`: combine HTML files into one EPUB collection.
- `WEREAD_COLLECTION_TITLE`: title for the combined EPUB.

## Notes

- PDF conversion requires `pymupdf`.
- HTML extraction works best with `beautifulsoup4`.
- Image dimension detection uses `Pillow` when available.
- DOCX/MOBI/PPT should be converted to HTML/PDF first, or handled by a richer local workflow.
- For very large image-heavy EPUBs, compress images before uploading to WeRead to avoid web import timeouts.

## Author and license

Designed by Xingyun and implemented with AI-assisted coding. See [LICENSE](LICENSE). Dependencies retain their respective licenses.
