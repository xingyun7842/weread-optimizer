from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import time
import unicodedata
import zipfile
from urllib.parse import unquote, urlparse
from collections import Counter, defaultdict
from pathlib import Path

try:
    from bs4 import BeautifulSoup, NavigableString
except Exception:
    BeautifulSoup = None
    NavigableString = None

try:
    import fitz
except Exception:
    fitz = None

try:
    from PIL import Image
except Exception:
    Image = None

ROOT = Path(os.environ.get("WEREAD_INPUT_DIR", Path.cwd())).resolve()
OUT = Path(os.environ.get("WEREAD_OUTPUT_DIR", ROOT / "微信读书优化输出")).resolve()
EPUB_DIR = OUT / "epub"
IMG_TMP = OUT / "_work_images"
REPORT = OUT / "处理报告.md"
MANIFEST = OUT / "manifest.json"
SOURCE_EXTS = {".html", ".htm", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}
HTML_EXTS = {".html", ".htm"}

NOISE_SELECTORS = "script,style,noscript,svg,canvas,iframe,video,audio,button,form,header,footer,nav,aside"
NOISE_CLASSES = ["advert", "ads", "share", "comment", "comments", "sidebar", "recommend", "footer", "header"]
INTERACTIVE_RE = re.compile(r"<\s*(video|audio|iframe)\b|\.mp4\b", re.I)
MEDIA_PLACEHOLDER_RE = re.compile(
    r"[\w.\-]+\.(?:mp4|m4v|mov|webm|mp3|m4a|wav|aac|flac)(?:\s*【在线播放】)?",
    re.I,
)


def safe_name(value: str, max_len: int = 96) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = "untitled"
    if len(value) > max_len:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
        value = value[: max_len - 9].rstrip() + "_" + digest
    return value


def source_sort_key(path: Path) -> tuple[int, int, str]:
    m = re.match(r"^\s*(\d{1,4})(?=\D|$)", path.name)
    if m:
        return (0, int(m.group(1)), path.name.lower())
    return (1, 10**9, path.name.lower())


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def iter_sources() -> list[Path]:
    html_only = os.environ.get("WEREAD_HTML_ONLY", "").lower() in {"1", "true", "yes"}
    sources = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        if html_only and path.suffix.lower() not in HTML_EXTS:
            continue
        if is_under(path, OUT):
            continue
        sources.append(path)
    return sorted(sources, key=source_sort_key)


def output_stem(source: Path) -> str:
    rel = source.relative_to(ROOT)
    base = source.stem if len(rel.parts) == 1 else "__".join(rel.with_suffix("").parts)
    m = re.match(r"^\s*(\d{1,4})(?=\D|$)", source.name)
    if m:
        rest = base[m.end():].strip(" -_—–.．、")
        return safe_name(f"{int(m.group(1)):02d}-{rest or base}")
    return safe_name(base)


def xhtml_doc(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN">\n'
        f'<head><title>{html.escape(title)}</title><meta charset="utf-8" />'
        '<link rel="stylesheet" type="text/css" href="../styles.css" /></head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def media_type(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext, "application/octet-stream")


def prepare_chapter_body_for_toc(body: str, chapter_index: int) -> tuple[str, list[tuple[str, str]]]:
    """Add stable ids to h2 headings so EPUB nav can link into each lesson."""
    if BeautifulSoup is None:
        return body, []
    soup = BeautifulSoup(body, "html.parser")
    headings: list[tuple[str, str]] = []
    for node in soup.find_all("h2"):
        text = clean_text(node.get_text(" ", strip=True))
        if not text or len(text) > 120:
            continue
        heading_id = node.get("id") or f"toc-c{chapter_index:02d}-h{len(headings)+1:03d}"
        node["id"] = heading_id
        headings.append((text, heading_id))
    return str(soup), headings


def write_epub(epub_path: Path, title: str, chapters: list[tuple[str, str]], images: list[tuple[Path, str]]) -> None:
    uid = hashlib.sha1((title + str(time.time())).encode("utf-8")).hexdigest()
    css = """
body{font-family:serif;line-height:1.78;margin:0 4%;color:#111}h1,h2,h3{line-height:1.35;text-indent:0;break-after:avoid;page-break-after:avoid}h1{font-size:1.45em;text-align:center;margin:1.2em 0 1em}h1.chapter-title{border-bottom:1px solid #ddd;padding-bottom:.55em}h2{font-size:1.25em;margin:1.35em 0 .7em}h3{font-size:1.08em;margin:1.05em 0 .45em}p{margin:.58em 0;text-indent:2em}p.noindent,.note,.scan-note,.callout p,.mobile-table-title,.mobile-table-row,.compare-block{ text-indent:0 }ul,ol{margin:.55em 0 .55em 1.45em;padding:0}li{margin:.25em 0;line-height:1.65}blockquote{margin:.8em 0 .8em .4em;padding-left:.8em;border-left:.18em solid #999;color:#444;text-indent:0}pre{white-space:pre-wrap;overflow-wrap:break-word;font-family:monospace;font-size:.88em;line-height:1.45;margin:.85em 0;padding:.65em;background:#f6f6f6;text-indent:0}code{font-family:monospace}strong{font-weight:700}em{font-style:italic}.underline{text-decoration:underline}.text-color-1{color:#d83931}.text-color-2{color:#de7802}.highlight-orange{background:#fff5eb}.callout{background:#fff5eb;border:1px solid #fed4a4;border-radius:.45em;margin:1em 0;padding:.75em .9em;text-indent:0}.callout p{margin:.25em 0}.section-heading{font-weight:700;text-indent:0;font-size:1.08em;margin:1.05em 0 .45em}.mobile-table-title{font-weight:700;margin:.95em 0 .25em;padding-bottom:.2em;border-bottom:1px solid #bbb}.mobile-table-row{margin:.25em 0;padding:.18em 0;border-bottom:1px solid #e5e5e5;line-height:1.65}.compare-block{margin:.55em 0;padding:.45em .6em;background:#f7f7f7}table{border-collapse:collapse;width:100%;margin:1em 0}td,th{border:1px solid #999;padding:.35em .45em;vertical-align:top;text-indent:0}th{font-weight:700;background:#f2f2f2}img{max-width:100%;height:auto;display:block;margin:.9em auto}.note,.scan-note{color:#666;font-size:.9em}
"""
    legacy_epub2 = os.environ.get("WEREAD_EPUB2", "").lower() in {"1", "true", "yes"}
    manifest = ['<item id="nav" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>', '<item id="css" href="styles.css" media-type="text/css"/>']
    spine = []
    nav_items = []
    chapter_files = []
    for index, (chapter_title, body) in enumerate(chapters, 1):
        href = f"text/part{index:04d}.xhtml"
        item_id = f"part{index:04d}"
        body, section_headings = prepare_chapter_body_for_toc(body, index)
        chapter_files.append((href, xhtml_doc(chapter_title, body)))
        manifest.append(f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{item_id}"/>')
        sub_items = "".join(
            f'<li><a href="{href}#{html.escape(anchor, quote=True)}">{html.escape(text)}</a></li>'
            for text, anchor in section_headings
        )
        if sub_items:
            nav_items.append(f'<li><a href="{href}">{html.escape(chapter_title)}</a><ol>{sub_items}</ol></li>')
        else:
            nav_items.append(f'<li><a href="{href}">{html.escape(chapter_title)}</a></li>')
    for index, (_, arcname) in enumerate(images, 1):
        manifest.append(f'<item id="img{index:05d}" href="{arcname}" media-type="{media_type(arcname)}"/>')
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>zh-CN</dc:language></metadata><manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>'''
    nav = xhtml_doc("目录", '<nav epub:type="toc" id="toc"><h1>目录</h1><ol>' + "".join(nav_items) + "</ol></nav>")
    container = '<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/toc.xhtml", nav)
        zf.writestr("OEBPS/styles.css", css)
        for href, content in chapter_files:
            zf.writestr("OEBPS/" + href, content)
        for source, arcname in images:
            zf.write(source, "OEBPS/" + arcname)


def write_epub2(epub_path: Path, title: str, chapters: list[tuple[str, str]], images: list[tuple[Path, str]]) -> None:
    uid = hashlib.sha1((title + str(time.time())).encode("utf-8")).hexdigest()
    css = """
body{font-family:serif;line-height:1.78;margin:0 4%;color:#111}h1,h2,h3{line-height:1.35;text-indent:0;page-break-after:avoid}h1{font-size:1.45em;text-align:center;margin:1.2em 0 1em}h1.chapter-title{border-bottom:1px solid #ddd;padding-bottom:.55em}h2{font-size:1.25em;margin:1.35em 0 .7em}h3{font-size:1.08em;margin:1.05em 0 .45em}p{margin:.58em 0;text-indent:2em}p.noindent,.callout p{ text-indent:0 }strong{font-weight:700}.text-color-1{color:#d83931}.text-color-2{color:#de7802}.highlight-orange{background:#fff5eb}.callout{background:#fff5eb;border:1px solid #fed4a4;margin:1em 0;padding:.75em .9em;text-indent:0}pre{white-space:pre-wrap;overflow-wrap:break-word;font-family:monospace;font-size:.88em;line-height:1.45;margin:.85em 0;padding:.65em;background:#f6f6f6;text-indent:0}table{border-collapse:collapse;width:100%;margin:1em 0}td,th{border:1px solid #999;padding:.35em .45em;vertical-align:top;text-indent:0}th{font-weight:700;background:#f2f2f2}img{max-width:100%;height:auto;display:block;margin:.9em auto}
"""
    manifest = ['<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', '<item id="css" href="styles.css" media-type="text/css"/>']
    spine = []
    chapter_files = []
    nav_points = []
    for index, (chapter_title, body) in enumerate(chapters, 1):
        href = f"text/part{index:04d}.xhtml"
        item_id = f"part{index:04d}"
        chapter_files.append((href, xhtml_doc(chapter_title, body)))
        manifest.append(f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{item_id}"/>')
        nav_points.append(f'<navPoint id="navPoint-{index}" playOrder="{index}"><navLabel><text>{html.escape(chapter_title)}</text></navLabel><content src="{href}"/></navPoint>')
    for index, (_, arcname) in enumerate(images, 1):
        manifest.append(f'<item id="img{index:05d}" href="{arcname}" media-type="{media_type(arcname)}"/>')
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>zh-CN</dc:language></metadata><manifest>{''.join(manifest)}</manifest><spine toc="ncx">{''.join(spine)}</spine></package>'''
    ncx = f'''<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="urn:uuid:{uid}"/></head><docTitle><text>{html.escape(title)}</text></docTitle><navMap>{''.join(nav_points)}</navMap></ncx>'''
    container = '<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/toc.ncx", ncx)
        zf.writestr("OEBPS/styles.css", css)
        for href, content in chapter_files:
            zf.writestr("OEBPS/" + href, content)
        for source, arcname in images:
            zf.write(source, "OEBPS/" + arcname)


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", "replace")


def save_data_image(src: str, img_dir: Path, stem: str, index: int) -> tuple[Path, str] | None:
    if not src.startswith("data:image/"):
        return None
    m = re.match(r"data:image/([a-zA-Z0-9.+-]+);base64,(.*)", src, re.S)
    if not m:
        return None
    ext = m.group(1).lower().split("+", 1)[0].replace("jpeg", "jpg")
    try:
        data = base64.b64decode(m.group(2), validate=False)
    except Exception:
        return None
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_name(f"{stem}_{index:04d}.{ext}", 120)
    out = img_dir / filename
    out.write_bytes(data)
    return out, f"images/{filename}"


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([，。！？：；、）】》”’])", r"\1", text)
    return text


def is_media_placeholder_text(text: str) -> bool:
    value = clean_text(text)
    if not value:
        return False
    if "【在线播放】" in value and MEDIA_PLACEHOLDER_RE.search(value):
        return True
    return MEDIA_PLACEHOLDER_RE.fullmatch(value) is not None


def class_names(node) -> set[str]:
    if not hasattr(node, "get"):
        return set()
    return {str(value) for value in (node.get("class") or [])}


def has_class(node, *names: str) -> bool:
    classes = class_names(node)
    return any(name in classes for name in names)


BLOCK_CONTAINER_CLASSES = {
    "callout",
    "table",
    "grid",
    "block-code",
    "block-image",
    "quote_container",
    "vc-quote_container",
}


def is_block_container(node) -> bool:
    if not getattr(node, "name", None):
        return False
    return node.name in {"table", "blockquote", "pre"} or bool(class_names(node) & BLOCK_CONTAINER_CLASSES)


def contains_block_container(node) -> bool:
    if not hasattr(node, "select_one"):
        return False
    selectors = ".callout, .table, .grid, .block-code, .block-image, .quote_container, .vc-quote_container, blockquote, pre, table"
    return node.select_one(selectors) is not None


def remove_media_placeholders(soup) -> None:
    if not hasattr(soup, "select"):
        return
    for tag in soup.select(".block-file, .file-card, .media-card"):
        classes = class_names(tag)
        text = tag.get_text(" ", strip=True)
        if {"video", "audio"} & classes or is_media_placeholder_text(text):
            tag.decompose()


def block_signature(fragment: str) -> str:
    if BeautifulSoup is not None:
        text = BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True)
    else:
        text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", "", html.unescape(text))


def dedupe_adjacent_blocks(blocks: list[str]) -> list[str]:
    result = []
    last_signature = ""
    for block in blocks:
        signature = block_signature(block)
        if signature and len(signature) >= 8 and signature == last_signature:
            continue
        result.append(block)
        last_signature = signature
    return result


def inline_node_html(node) -> str:
    if NavigableString is not None and isinstance(node, NavigableString):
        return html.escape(re.sub(r"\s+", " ", str(node)))
    if not getattr(node, "name", None):
        return ""
    if node.name == "br":
        return "<br/>"
    if node.name == "img":
        return ""
    inner = "".join(inline_node_html(child) for child in node.children)
    if not inner:
        return ""
    classes = class_names(node)
    if node.name == "a" and node.get("href"):
        href = html.escape(node.get("href", ""), quote=True)
        inner = f'<a href="{href}">{inner}</a>'
    if node.name == "code":
        inner = f"<code>{inner}</code>"
    if "background_color_2" in classes:
        inner = f'<span class="highlight-orange">{inner}</span>'
    if "text_color_1" in classes:
        inner = f'<span class="text-color-1">{inner}</span>'
    elif "text_color_2" in classes:
        inner = f'<span class="text-color-2">{inner}</span>'
    if "underline" in classes:
        inner = f'<span class="underline">{inner}</span>'
    if node.name in {"i", "em"} or "italic" in classes:
        inner = f"<em>{inner}</em>"
    if node.name in {"b", "strong"} or "bold" in classes or "font-bold" in classes or "font-semibold" in classes:
        inner = f"<strong>{inner}</strong>"
    return inner


def rich_text_html(node) -> str:
    targets = []
    marker_text = ""
    if hasattr(node, "select"):
        for block in node.select(".block-text"):
            if block.find_parent(class_="vc-doc-item") is node:
                targets.append(block)
    if not targets and hasattr(node, "select_one"):
        list_target = node.select_one(".row > .list") or node.select_one(".list")
        if list_target is not None and list_target.find_parent(class_="vc-doc-item") is node:
            marker = node.select_one(".order-marker") or node.select_one(".bullet-marker")
            if marker is not None:
                marker_text = clean_text(marker.get_text(" ", strip=True))
            targets.append(list_target)
    if not targets:
        targets = [node]
    value = "<br/>".join("".join(inline_node_html(child) for child in target.children).strip() for target in targets if target).strip()
    if marker_text and value and not value.startswith(marker_text):
        value = f"{html.escape(marker_text)} {value}"
    return value


def html_cell(cell) -> str:
    value = rich_text_html(cell)
    return value or html.escape(clean_text(cell.get_text(" ", strip=True)))


def convert_callout(node) -> str:
    parts = []
    for item in direct_vc_items(node):
        value = rich_text_html(item)
        if value:
            parts.append(value)
    if not parts:
        fallback = rich_text_html(node) or html.escape(clean_text(node.get_text(" ", strip=True)))
        if fallback:
            parts.append(fallback)
    return '<div class="callout">' + "".join(f'<p class="noindent">{part}</p>' for part in parts) + "</div>" if parts else ""


def direct_vc_items(node) -> list:
    items = []
    for item in node.select(".vc-doc-item") if hasattr(node, "select") else []:
        parent = item.parent
        nested = False
        while parent is not None and parent is not node:
            if has_class(parent, "vc-doc-item"):
                nested = True
                break
            parent = parent.parent
        if not nested:
            items.append(item)
    return items


def convert_quote(node) -> str:
    parts = []
    for item in direct_vc_items(node):
        value = rich_text_html(item)
        if value:
            parts.append(value)
    if not parts:
        value = rich_text_html(node) or html.escape(clean_text(node.get_text(" ", strip=True)))
        if value:
            parts.append(value)
    return "<blockquote>" + "".join(f'<p class="noindent">{part}</p>' for part in parts) + "</blockquote>" if parts else ""


def convert_block_code(node) -> str:
    code_node = None
    if hasattr(node, "select_one"):
        code_node = node.select_one(".block-code-content code") or node.select_one("pre code") or node.select_one("code") or node.select_one("pre")
    code_node = code_node or node
    code = code_node.get_text("\n").strip()
    return f"<pre>{html.escape(code)}</pre>" if code else ""


def convert_images(node, img_dir: Path, stem: str, image_index: int) -> tuple[list[str], list[tuple[Path, str]], int]:
    blocks = []
    images = []
    candidates = ([node] if getattr(node, "name", None) == "img" else []) + node.find_all("img")
    for img in candidates:
        saved = save_data_image(img.get("src", ""), img_dir, stem, image_index + 1)
        if saved:
            image_index += 1
            images.append(saved)
            blocks.append(f'<p class="noindent"><img src="../{html.escape(saved[1])}" alt="image {image_index}" /></p>')
    return blocks, images, image_index


def block_header_html(node) -> str:
    target = node.select_one(".block-header") if hasattr(node, "select_one") else None
    if target is None and has_class(node, "block-header", "block6"):
        target = node
    if target is None:
        return ""
    value = rich_text_html(target)
    text_value = clean_text(target.get_text(" ", strip=True))
    return f'<p class="section-heading"><strong>{value or html.escape(text_value)}</strong></p>' if text_value else ""


def inside_classed_parent(node, root, *names: str) -> bool:
    parent = node.parent
    while parent is not None and parent is not root:
        if has_class(parent, *names):
            return True
        parent = parent.parent
    return False


def inside_block_container(node, root) -> bool:
    parent = node.parent
    while parent is not None and parent is not root:
        if is_block_container(parent):
            return True
        parent = parent.parent
    return False


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [html_cell(c) for c in cells[start:start+cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""

    if cols == 2 and len(rows[0]) >= 2:
        parts = [f'<p class="mobile-table-title"><strong>{rows[0][0]} / {rows[0][1]}</strong></p>']
        for row in rows[1:]:
            padded = row + [""] * max(0, cols - len(row))
            key, value = padded[0], padded[1]
            if key and value:
                parts.append(f'<p class="mobile-table-row"><strong>{key}：</strong>{value}</p>')
            elif key or value:
                parts.append(f'<p class="mobile-table-row">{key or value}</p>')
        return "".join(parts)

    parts = []
    for row_index, row in enumerate(rows):
        text = " / ".join(value for value in row if value)
        if not text:
            continue
        cls = "mobile-table-title" if row_index == 0 else "mobile-table-row"
        tag_open = "<strong>" if row_index == 0 else ""
        tag_close = "</strong>" if row_index == 0 else ""
        parts.append(f'<p class="{cls}">{tag_open}{text}{tag_close}</p>')
    return "".join(parts)


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [html_cell(c) for c in cells[start:start + cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""
    table_style = "border-collapse:collapse;width:100%;margin:1em 0;table-layout:fixed"
    cell_base = "border:1px solid #999;padding:.35em .45em;vertical-align:top;text-indent:0;line-height:1.45;word-break:break-word"
    rendered_rows = []
    for row_index, row in enumerate(rows):
        padded = row + [""] * max(0, cols - len(row))
        cells_html = []
        for col_index, value in enumerate(padded[:cols]):
            tag = "th" if row_index == 0 else "td"
            width = f"{100 // max(cols, 1)}%"
            if cols == 2:
                width = "34%" if col_index == 0 else "66%"
            style = cell_base
            if row_index == 0:
                style += ";font-weight:700;background:#f2f2f2"
            cells_html.append(f'<{tag} width="{width}" style="{style}">{value}</{tag}>')
        rendered_rows.append("<tr>" + "".join(cells_html) + "</tr>")
    return f'<table class="data-table" border="1" cellspacing="0" cellpadding="6" width="100%" style="{table_style}">' + "".join(rendered_rows) + "</table>"


def convert_grid(node, img_dir: Path, stem: str, image_index: int) -> tuple[str, list[tuple[Path, str]], int]:
    images = []
    cols = node.select(".grid_column") or node.find_all(recursive=False)
    cells = []
    for col in cols:
        parts = []
        for img in col.find_all("img"):
            saved = save_data_image(img.get("src", ""), img_dir, stem, image_index + 1)
            if saved:
                image_index += 1
                images.append(saved)
                parts.append(f'<img src="../{html.escape(saved[1])}" alt="图 {image_index}" />')
        text = rich_text_html(col)
        if text:
            parts.append(text)
        if parts:
            cells.append("<br/>".join(parts))
    if len(cells) >= 2:
        return "".join(f'<p class="compare-block">{c}</p>' for c in cells), images, image_index
    return "".join(f'<p class="noindent">{c}</p>' for c in cells), images, image_index


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [html_cell(c) for c in cells[start:start + cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""

    def cell(tag: str, value: str, index: int, total: int) -> str:
        width = f"{100 / max(total, 1):.2f}%"
        if total == 2:
            width = "34%" if index == 0 else "66%"
        style = f"border:1px solid #999;padding:.35em .45em;vertical-align:top;text-indent:0;line-height:1.45;width:{width};word-break:break-word"
        if index == 0:
            style += ";white-space:nowrap;word-break:keep-all"
        return f'<{tag} style="{style}">{value}</{tag}>'

    def row_table(row: list[str], row_index: int) -> str:
        padded = row + [""] * max(0, cols - len(row))
        tag = "th" if row_index == 0 else "td"
        table_style = "border-collapse:collapse;width:100%;margin:.12em 0;page-break-inside:avoid;break-inside:avoid"
        return (
            f'<table class="data-row-table" border="1" cellspacing="0" cellpadding="4" style="{table_style}"><tr>'
            + "".join(cell(tag, value, index, cols) for index, value in enumerate(padded[:cols]))
            + "</tr></table>"
        )

    return '<div class="data-table-group">' + "".join(row_table(row, index) for index, row in enumerate(rows)) + "</div>"


def convert_grid(node, img_dir: Path, stem: str, image_index: int) -> tuple[str, list[tuple[Path, str]], int]:
    images = []
    cols = node.select(".grid_column") or node.find_all(recursive=False)
    cells = []
    for col in cols:
        parts = []
        for img in col.find_all("img"):
            saved = save_data_image(img.get("src", ""), img_dir, stem, image_index + 1)
            if saved:
                image_index += 1
                images.append(saved)
                parts.append(f'<img src="../{html.escape(saved[1])}" alt="image {image_index}" />')
        text = rich_text_html(col)
        if text:
            parts.append(text)
        if parts:
            cells.append("<br/>".join(parts))
    if len(cells) >= 2:
        table_style = "border-collapse:collapse;width:100%;margin:.35em 0;page-break-inside:avoid;break-inside:avoid"
        cell_style = "border:1px solid #999;padding:.35em .45em;vertical-align:top;text-indent:0;line-height:1.45;word-break:break-word"
        return (
            f'<table class="compare-table" border="1" cellspacing="0" cellpadding="4" style="{table_style}"><tr>'
            + "".join(f'<td style="{cell_style}">{c}</td>' for c in cells)
            + "</tr></table>"
        ), images, image_index
    return "".join(f'<p class="noindent">{c}</p>' for c in cells), images, image_index


def visual_table_row(cells: list[str], cols: int, is_header: bool = False) -> str:
    row_style = (
        "display:block;width:100%;box-sizing:border-box;border-left:1px solid #999;"
        "border-right:1px solid #999;border-top:1px solid #999;font-size:0;"
        "page-break-inside:avoid;break-inside:avoid"
    )
    parts = []
    padded = cells + [""] * max(0, cols - len(cells))
    for index, value in enumerate(padded[:cols]):
        width = f"{100 / max(cols, 1):.2f}%"
        if cols == 2:
            width = "34%" if index == 0 else "66%"
        style = (
            f"display:inline-block;box-sizing:border-box;width:{width};padding:.35em .45em;"
            "vertical-align:top;text-indent:0;line-height:1.45;font-size:1em;word-break:break-word"
        )
        if index < cols - 1:
            style += ";border-right:1px solid #999"
        if index == 0:
            style += ";white-space:nowrap;word-break:keep-all"
        content = f"<strong>{value}</strong>" if is_header else value
        parts.append(f'<span style="{style}">{content}</span>')
    return f'<div class="visual-table-row" style="{row_style}">' + "".join(parts) + "</div>"


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [html_cell(c) for c in cells[start:start + cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""
    group_style = "display:block;width:100%;margin:.8em 0;border-bottom:1px solid #999"
    body = "".join(visual_table_row(row, cols, index == 0) for index, row in enumerate(rows))
    return f'<div class="visual-table-group" style="{group_style}">{body}</div>'


def convert_grid(node, img_dir: Path, stem: str, image_index: int) -> tuple[str, list[tuple[Path, str]], int]:
    images = []
    cols = node.select(".grid_column") or node.find_all(recursive=False)
    cells = []
    for col in cols:
        parts = []
        for img in col.find_all("img"):
            saved = save_data_image(img.get("src", ""), img_dir, stem, image_index + 1)
            if saved:
                image_index += 1
                images.append(saved)
                parts.append(f'<img src="../{html.escape(saved[1])}" alt="image {image_index}" />')
        text = rich_text_html(col)
        if text:
            parts.append(text)
        if parts:
            cells.append("<br/>".join(parts))
    if len(cells) >= 2 and not any(block_signature(cell) for cell in cells):
        return "".join(f'<p class="noindent">{cell}</p>' for cell in cells), images, image_index
    if len(cells) >= 2:
        group_style = "display:block;width:100%;margin:.8em 0;border-bottom:1px solid #999"
        return f'<div class="visual-table-group" style="{group_style}">{visual_table_row(cells, len(cells), False)}</div>', images, image_index
    return "".join(f'<p class="noindent">{c}</p>' for c in cells), images, image_index


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [html_cell(c) for c in cells[start:start + cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""
    if cols == 2 and len(rows[0]) >= 2:
        parts = [f'<p class="mobile-table-title"><strong>{rows[0][0]} / {rows[0][1]}</strong></p>']
        for row in rows[1:]:
            key = row[0] if row else ""
            value = row[1] if len(row) > 1 else ""
            if key and value:
                parts.append(f'<p class="mobile-table-row"><strong>{key}：</strong>{value}</p>')
            else:
                parts.append(f'<p class="mobile-table-row">{key or value}</p>')
        return "".join(parts)
    parts = []
    for row_index, row in enumerate(rows):
        text = " / ".join(value for value in row if value)
        if not text:
            continue
        cls = "mobile-table-title" if row_index == 0 else "mobile-table-row"
        content = f"<strong>{text}</strong>" if row_index == 0 else text
        parts.append(f'<p class="{cls}">{content}</p>')
    return "".join(parts)


def convert_grid(node, img_dir: Path, stem: str, image_index: int) -> tuple[str, list[tuple[Path, str]], int]:
    images = []
    cols = node.select(".grid_column") or node.find_all(recursive=False)
    cells = []
    for col in cols:
        parts = []
        for img in col.find_all("img"):
            saved = save_data_image(img.get("src", ""), img_dir, stem, image_index + 1)
            if saved:
                image_index += 1
                images.append(saved)
                parts.append(f'<img src="../{html.escape(saved[1])}" alt="image {image_index}" />')
        text = rich_text_html(col)
        if text:
            parts.append(text)
        if parts:
            cells.append("<br/>".join(parts))
    if len(cells) >= 2 and not any(block_signature(cell) for cell in cells):
        return "".join(f'<p class="noindent">{cell}</p>' for cell in cells), images, image_index
    if len(cells) >= 2:
        body = "".join(f'<p class="noindent">{cell}</p>' for cell in cells)
        return f'<div class="compare-block">{body}</div>', images, image_index
    return "".join(f'<p class="noindent">{c}</p>' for c in cells), images, image_index


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [html_cell(c) for c in cells[start:start + cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""
    table_style = "border-collapse:collapse;width:100%;margin:1em 0;table-layout:fixed"
    cell_base = "border:1px solid #999;padding:.35em .45em;vertical-align:top;text-indent:0;line-height:1.45;word-break:break-word"
    rendered_rows = []
    for row_index, row in enumerate(rows):
        padded = row + [""] * max(0, cols - len(row))
        cells_html = []
        for col_index, value in enumerate(padded[:cols]):
            tag = "th" if row_index == 0 else "td"
            width = f"{100 // max(cols, 1)}%"
            if cols == 2:
                width = "34%" if col_index == 0 else "66%"
            style = cell_base
            if row_index == 0:
                style += ";font-weight:700;background:#f2f2f2"
            cells_html.append(f'<{tag} width="{width}" style="{style}">{value}</{tag}>')
        rendered_rows.append("<tr>" + "".join(cells_html) + "</tr>")
    return f'<table class="data-table" border="1" cellspacing="0" cellpadding="6" width="100%" style="{table_style}">' + "".join(rendered_rows) + "</table>"


def plain_text_from_html(value: str) -> str:
    if BeautifulSoup is None:
        return clean_text(re.sub(r"<[^>]+>", " ", value))
    return clean_text(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))


def display_width(value: str) -> int:
    total = 0
    for char in value:
        total += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return total


def pad_display(value: str, width: int) -> str:
    return value + " " * max(0, width - display_width(value))


def wrap_display(value: str, width: int) -> list[str]:
    value = clean_text(value)
    if not value:
        return [""]
    lines = []
    current = ""
    current_width = 0
    for char in value:
        char_width = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if current and current_width + char_width > width:
            lines.append(current)
            current = char
            current_width = char_width
        else:
            current += char
            current_width += char_width
    lines.append(current)
    return lines


def convert_table(node) -> str:
    cells = node.select(".table_cell") or node.find_all(["td", "th"])
    if not cells:
        return ""
    cols = 2
    for cls in node.get("class", []):
        m = re.fullmatch(r"table_(\d+)", str(cls))
        if m:
            cols = max(1, int(m.group(1)))
    rows = []
    for start in range(0, len(cells), cols):
        values = [plain_text_from_html(html_cell(c)) for c in cells[start:start + cols]]
        if any(values):
            rows.append(values)
    if not rows:
        return ""
    if cols == 2:
        widths = [10, 28]
    elif cols == 3:
        widths = [10, 16, 16]
    else:
        widths = [10] + [14] * (cols - 1)
    widths = widths[:cols]
    gap = "  "
    lines = []
    for row_index, row in enumerate(rows):
        padded = row + [""] * max(0, cols - len(row))
        wrapped = [wrap_display(padded[index], widths[index]) for index in range(cols)]
        height = max(len(part) for part in wrapped)
        for line_index in range(height):
            pieces = []
            for col_index in range(cols):
                text = wrapped[col_index][line_index] if line_index < len(wrapped[col_index]) else ""
                pieces.append(pad_display(text, widths[col_index]))
            lines.append(gap.join(pieces).rstrip())
        if row_index == 0:
            lines.append(gap.join("-" * width for width in widths).rstrip())
    body = "\n".join(lines)
    style = "font-family:monospace;font-size:.78em;line-height:1.45;white-space:pre-wrap;text-indent:0;background:#f7f7f7;padding:.55em .65em;margin:.8em 0"
    return f'<pre class="text-table" style="{style}">{html.escape(body)}</pre>'


def content_root(soup):
    for selector in ("main.content", "main", ".max-w-4xl", "article", ".ql-editor", ".markdown-body", "[class*=markdown]"):
        root = soup.select_one(selector)
        if root and clean_text(root.get_text(" ", strip=True)):
            return root
    return soup.body or soup


def html_items(soup):
    root = content_root(soup)
    selectors = [
        ".level2-section > h2",
        ".level3-section > h3",
        ".level3-section > h4",
        ".callout",
        ".block-code",
        ".block-image",
        ".quote_container",
        ".vc-quote_container",
        ".table",
        ".grid",
        ".vc-doc-item",
        "table",
        "blockquote",
        "pre",
    ]
    items = root.select(", ".join(selectors))
    has_custom_blocks = bool(root.select(".level2-section, .level3-section, .callout, .block-code, .block-image, .quote_container, .vc-quote_container, .table, .grid, .vc-doc-item"))
    if not items or not has_custom_blocks:
        items = root.select("h1, h2, h3, h4, h5, h6, p, ul, ol, figure, img, .callout, .block-code, .block-image, .quote_container, .vc-quote_container, .table, .grid, .vc-doc-item, table, blockquote, pre")
    filtered = []
    for item in items:
        if any(parent in items for parent in item.parents if parent is not root):
            continue
        if is_media_placeholder_text(item.get_text(" ", strip=True)):
            continue
        if inside_block_container(item, root):
            continue
        if has_class(item, "vc-doc-item") and contains_block_container(item):
            continue
        filtered.append(item)
    return filtered or [root]


def extract_html(source: Path) -> tuple[str, str, list[tuple[Path, str]], list[str]]:
    text = read_text(source)
    interactive = ["HTML interactive/media"] if INTERACTIVE_RE.search(text) else []
    if BeautifulSoup is None:
        return source.stem, f"<pre>{html.escape(text)}</pre>", [], interactive
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title and soup.title.get_text(strip=True) else source.stem
    for image in soup.find_all("img"):
        image_src = image.get("src", "")
        if image_src.startswith("data:image/"):
            continue
        parsed = urlparse(image_src)
        local = (source.parent / unquote(parsed.path)).resolve() if not parsed.scheme and not parsed.netloc else None
        if local is not None and is_under(local, ROOT) and local.is_file() and local.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            image["src"] = "data:" + media_type(local.name) + ";base64," + base64.b64encode(local.read_bytes()).decode("ascii")
        else:
            note = soup.new_tag("p", attrs={"class": "note"})
            note.string = "[图片未嵌入：请先将原图保存在输入目录内，并使用有效的本地图片路径。]"
            image.replace_with(note)
    for media in soup.find_all(["video", "audio", "iframe"]):
        note = soup.new_tag("p", attrs={"class": "note"})
        note.string = "[原文含视频、音频或交互组件；EPUB 保留静态内容，未嵌入该媒体。]"
        media.replace_with(note)
    for tag in soup.select(NOISE_SELECTORS):
        tag.decompose()
    remove_media_placeholders(soup)
    for cls in NOISE_CLASSES:
        for tag in soup.select(f".{cls}"):
            tag.decompose()
    img_dir = IMG_TMP / safe_name(source.stem)
    images = []
    blocks = []
    image_index = 0
    items = html_items(soup)
    for item in items:
        classes = item.get("class", []) if hasattr(item, "get") else []
        text_value = clean_text(item.get_text(" ", strip=True))
        if item.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if text_value:
                tag = "h2" if item.name in {"h1", "h2"} else "h3"
                blocks.append(f"<{tag}>{html.escape(text_value)}</{tag}>")
            continue
        if "callout" in classes:
            callout_html = convert_callout(item)
            if callout_html:
                blocks.append(callout_html)
            continue
        if item.name == "table" or "table" in classes:
            table_html = convert_table(item)
            if table_html:
                blocks.append(table_html)
            continue
        if "grid" in classes:
            grid_html, grid_images, image_index = convert_grid(item, img_dir, safe_name(source.stem), image_index)
            blocks.append(grid_html)
            images.extend(grid_images)
            continue
        if "block-code" in classes:
            code_html = convert_block_code(item)
            if code_html:
                blocks.append(code_html)
            continue
        if "block-image" in classes:
            image_blocks, image_entries, image_index = convert_images(item, img_dir, safe_name(source.stem), image_index)
            blocks.extend(image_blocks)
            images.extend(image_entries)
            continue
        if item.name == "blockquote" or "quote_container" in classes or "vc-quote_container" in classes:
            quote_html = convert_quote(item)
            if quote_html:
                blocks.append(quote_html)
            continue
        if item.name == "pre" or item.find("pre"):
            code = (item.find("pre") or item).get_text("\n").strip()
            if code:
                blocks.append(f"<pre>{html.escape(code)}</pre>")
            continue
        image_blocks, image_entries, image_index = convert_images(item, img_dir, safe_name(source.stem), image_index)
        blocks.extend(image_blocks)
        images.extend(image_entries)
        heading_html = block_header_html(item)
        if heading_html:
            blocks.append(heading_html)
            continue
        for img in ():
            saved = save_data_image(img.get("src", ""), img_dir, safe_name(source.stem), image_index + 1)
            if saved:
                image_index += 1
                images.append(saved)
                blocks.append(f'<p class="noindent"><img src="../{html.escape(saved[1])}" alt="图 {image_index}" /></p>')
        inline_value = rich_text_html(item)
        if not text_value or text_value in {"•", "-", "—"}:
            continue
        if is_media_placeholder_text(text_value):
            continue
        if item.find(["h1", "h2"]):
            blocks.append(f"<h2>{inline_value or html.escape(text_value)}</h2>")
        elif item.find(["h3", "h4"]):
            blocks.append(f"<h3>{inline_value or html.escape(text_value)}</h3>")
        elif re.fullmatch(r"https?://\S+", text_value):
            blocks.append(f'<p class="noindent"><a href="{html.escape(text_value, quote=True)}">{inline_value or html.escape(text_value)}</a></p>')
        else:
            blocks.append(f"<p>{inline_value or html.escape(text_value)}</p>")
    blocks = dedupe_adjacent_blocks(blocks)
    return title, "\n".join(blocks) or f"<p>{html.escape(clean_text((soup.body or soup).get_text(' ', strip=True)))}</p>", images, interactive


def chapter_title(source: Path, fallback: str) -> str:
    title = re.sub(r"\s+", " ", source.stem.replace("_", "/")).strip()
    m = re.match(r"^\s*(\d{1,4})(?=\D|$)", title)
    if m:
        rest = title[m.end():].strip(" -_—–.．、")
        title = f"{int(m.group(1)):02d} {rest or title}"
    return title or fallback or source.stem


def write_book(epub_path: Path, title: str, chapters: list[tuple[str, str]], images: list[tuple[Path, str]]) -> None:
    if os.environ.get("WEREAD_EPUB2", "").lower() in {"1", "true", "yes"}:
        write_epub2(epub_path, title, chapters, images)
    else:
        write_epub(epub_path, title, chapters, images)


def convert_html(source: Path, out_epub: Path) -> dict:
    title, body, images, interactive = extract_html(source)
    title = chapter_title(source, title)
    body = f'<h1 class="chapter-title">{html.escape(title)}</h1>\n' + body
    write_book(out_epub, title, [(title, body)], images)
    return result(source, out_epub, pages=1, images=len(images), interactive=interactive)


def convert_html_collection(sources: list[Path], out_epub: Path, title: str) -> dict:
    chapters = []
    images = []
    interactive = []
    for source in sources:
        fallback, body, img_entries, hits = extract_html(source)
        ctitle = chapter_title(source, fallback)
        chapters.append((ctitle, f'<h1 class="chapter-title">{html.escape(ctitle)}</h1>\n{body}'))
        images.extend(img_entries)
        interactive.extend([f"{source.name}: {hit}" for hit in hits])
    write_book(out_epub, title, chapters, images)
    return result(ROOT, out_epub, pages=len(chapters), images=len(images), interactive=interactive, sources=[str(p) for p in sources])


def text_body(text: str, title: str) -> str:
    blocks = [f'<h1 class="chapter-title">{html.escape(title)}</h1>']
    paragraphs = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for para in paragraphs:
        value = clean_text(para)
        if not value:
            continue
        if len(value) <= 70 and re.match(r"^(第.+[章节篇回]|[一二三四五六七八九十]+[、.．]|[0-9]{1,3}[、.．]|【.+】)", value):
            blocks.append(f"<h2>{html.escape(value)}</h2>")
        else:
            blocks.append(f"<p>{html.escape(value)}</p>")
    return "\n".join(blocks)


def convert_txt(source: Path, out_epub: Path) -> dict:
    title = chapter_title(source, source.stem)
    write_book(out_epub, title, [(title, text_body(read_text(source), title))], [])
    return result(source, out_epub, pages=1)


def convert_image(source: Path, out_epub: Path) -> dict:
    img_dir = IMG_TMP / safe_name(source.stem)
    img_dir.mkdir(parents=True, exist_ok=True)
    dest = img_dir / safe_name(source.name, 120)
    shutil.copy2(source, dest)
    arc = "images/" + dest.name
    size = "unknown"
    if Image is not None:
        try:
            with Image.open(source) as im:
                size = f"{im.width}x{im.height}"
        except Exception:
            pass
    title = chapter_title(source, source.stem)
    body = f'<h1 class="chapter-title">{html.escape(title)}</h1><p class="scan-note">[源文件是图片，已保留为整页图片；可查看和放大，但微信读书语音朗读无法读取图片中的文字。尺寸：{html.escape(size)}]</p><img src="../{html.escape(arc)}" alt="{html.escape(title)}" />'
    write_book(out_epub, title, [(title, body)], [(dest, arc)])
    return result(source, out_epub, pages=1, images=1, scan_pages=1, warnings=["源文件是图片，无文本层"])


def convert_pdf(source: Path, out_epub: Path) -> dict:
    if fitz is None:
        raise RuntimeError("缺少 pymupdf，无法转换 PDF")
    doc = fitz.open(str(source))
    img_dir = IMG_TMP / safe_name(source.stem)
    img_dir.mkdir(parents=True, exist_ok=True)
    chapters = []
    images = []
    scan_pages = 0
    for page_index, page in enumerate(doc, 1):
        text = clean_text(page.get_text("text"))
        if text:
            body = "\n".join(f"<p>{html.escape(p)}</p>" for p in re.split(r"(?<=[。！？])\s+", text) if p.strip())
        else:
            scan_pages += 1
            pix = page.get_pixmap(matrix=fitz.Matrix(1.65, 1.65), alpha=False)
            filename = f"{safe_name(source.stem, 40)}_p{page_index:04d}.jpg"
            img_path = img_dir / filename
            pix.save(str(img_path), jpg_quality=82)
            arc = "images/" + filename
            images.append((img_path, arc))
            body = f'<p class="scan-note">[扫描页 {page_index}：没有可抽取文本层，已按整页图片保留。]</p><img src="../{html.escape(arc)}" alt="扫描页 {page_index}" />'
        if page_index == 1:
            body = f'<h1 class="chapter-title">{html.escape(source.stem)}</h1>\n' + body
        if page_index % 80 == 1:
            chapters.append((f"{source.stem} - 第 {len(chapters)+1} 部分", body))
        else:
            title, old = chapters[-1]
            chapters[-1] = (title, old + "\n" + body)
    write_book(out_epub, source.stem, chapters or [(source.stem, f"<p>{html.escape(source.stem)}</p>")], images)
    return result(source, out_epub, pages=doc.page_count, images=len(images), scan_pages=scan_pages)


def result(source: Path, epub: Path, pages: int = 0, images: int = 0, scan_pages: int = 0, interactive: list[str] | None = None, warnings: list[str] | None = None, sources: list[str] | None = None) -> dict:
    row = {"source": str(source), "epub": str(epub), "status": "ok", "pages": pages, "images_kept": images, "images_removed": 0, "scan_pages": scan_pages, "interactive": interactive or [], "warnings": warnings or []}
    if sources:
        row["sources"] = sources
    return row


def write_report(sources: list[Path], rows: list[dict], elapsed: float) -> None:
    ok = [r for r in rows if r.get("status") == "ok"]
    failed = [r for r in rows if r.get("status") != "ok"]
    numbered: dict[int, list[str]] = defaultdict(list)
    for path in sources:
        m = re.match(r"^\s*(\d{1,4})(?=\D|$)", path.name)
        if m:
            numbered[int(m.group(1))].append(path.name)
    max_number = max(numbered) if numbered else 0
    missing = [str(i) for i in range(1, max_number + 1) if i not in numbered] if max_number else []
    duplicates = {k: v for k, v in numbered.items() if len(v) > 1}
    lines = ["# 微信读书优化处理报告", "", f"- 源目录：`{ROOT}`", f"- 输出目录：`{OUT}`", f"- 源文件数：{len(sources)}", f"- 成功生成 EPUB：{len(ok)}", f"- 失败：{len(failed)}", f"- 保留图片：{sum(r.get('images_kept', 0) for r in ok)}", f"- 扫描/图片页：{sum(r.get('scan_pages', 0) for r in ok)}", f"- 用时：{elapsed/60:.1f} 分钟", "", "## 编号检查", "", f"- 缺少序号：{', '.join(missing) if missing else '无'}"]
    if duplicates:
        lines.append("- 重复序号：" + "；".join(f"{k}: {', '.join(v)}" for k, v in sorted(duplicates.items())))
    interactive = [r for r in ok if r.get("interactive")]
    lines += ["", "## 交互组件检查", ""]
    if interactive:
        lines.append("检测到交互/媒体标记；EPUB 已保留正文与静态图片，交互媒体未嵌入。")
        for row in interactive:
            lines.append(f"- {Path(row['source']).name}：{', '.join(row.get('interactive', []))}")
    else:
        lines.append("未检测到 video/audio/iframe/mp4 等交互媒体标记。")
    if failed:
        lines += ["", "## 失败文件", ""]
        for row in failed:
            lines.append(f"- {Path(row['source']).name}：{row.get('error')}")
    lines += ["", "## 输出清单", ""]
    for row in rows:
        if row.get("status") == "ok":
            lines.append(f"- `{Path(row['epub']).name}` ← `{Path(row['source']).name}`")
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    EPUB_DIR.mkdir(parents=True, exist_ok=True)
    IMG_TMP.mkdir(parents=True, exist_ok=True)
    sources = iter_sources()
    rows = []
    start = time.time()
    if os.environ.get("WEREAD_COMBINE_HTML", "").lower() in {"1", "true", "yes"}:
        html_sources = [p for p in sources if p.suffix.lower() in HTML_EXTS]
        title = os.environ.get("WEREAD_COLLECTION_TITLE", ROOT.name or "合集")
        rows.append(convert_html_collection(html_sources, EPUB_DIR / f"{safe_name(title)}.epub", title))
    else:
        counts = Counter(output_stem(p) for p in sources)
        for source in sources:
            stem = output_stem(source)
            if counts[stem] > 1:
                stem = safe_name(f"{stem}__{source.suffix.lower().lstrip('.')}")
            out_epub = EPUB_DIR / f"{stem}.epub"
            try:
                ext = source.suffix.lower()
                if ext in HTML_EXTS:
                    row = convert_html(source, out_epub)
                elif ext == ".txt":
                    row = convert_txt(source, out_epub)
                elif ext == ".pdf":
                    row = convert_pdf(source, out_epub)
                elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
                    row = convert_image(source, out_epub)
                else:
                    raise RuntimeError(f"暂不支持的文件类型：{ext}")
            except Exception as exc:
                row = {"source": str(source), "epub": str(out_epub), "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            MANIFEST.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(sources, rows, time.time() - start)
    print(f"Done. EPUB: {EPUB_DIR}")
    print(f"Report: {REPORT}")
    return 0 if all(r.get("status") == "ok" for r in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
