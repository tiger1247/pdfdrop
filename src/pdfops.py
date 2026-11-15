"""PDFDrop toolkit operations. Pure functions on files; no UI code.

Every function writes new files and never modifies its inputs.
"""
import io
import os

import pymupdf

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
PAPER = {"A4": pymupdf.paper_rect("a4"), "Letter": pymupdf.paper_rect("letter")}


class PasswordNeeded(Exception):
    pass


def open_pdf(path, password=None):
    doc = pymupdf.open(path)
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise PasswordNeeded(os.path.basename(path))
    if not doc.is_pdf:  # e.g. an image or XPS opened by mistake
        pdf = pymupdf.open("pdf", doc.convert_to_pdf())
        doc.close()
        return pdf
    return doc


def parse_ranges(text, page_count):
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, 8, ...] (0-based, in the order given). Raises ValueError."""
    text = (text or "").replace(" ", "")
    if not text or text.lower() == "all":
        return list(range(page_count))
    pages = []
    for part in text.split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else page_count
        else:
            a = b = int(part)
        if not (1 <= a <= page_count and 1 <= b <= page_count):
            raise ValueError(f"Page {a if not 1 <= a <= page_count else b} doesn't exist (this PDF has {page_count} pages).")
        step = 1 if b >= a else -1
        pages.extend(range(a - 1, b - 1 + step, step))
    if not pages:
        raise ValueError("No pages selected.")
    return pages


def _save(doc, out, **kw):
    tmp = out + ".part"
    opts = dict(garbage=3, deflate=True)
    opts.update(kw)
    doc.save(tmp, **opts)
    doc.close()
    os.replace(tmp, out)
    return out


def merge(paths, out, passwords=None, progress=None):
    res = pymupdf.open()
    for i, p in enumerate(paths):
        ext = os.path.splitext(p)[1].lower()
        if ext in IMAGE_EXT:
            res.insert_pdf(_image_doc(p, "Fit"))
        else:
            src = open_pdf(p, (passwords or {}).get(p))
            res.insert_pdf(src)
            src.close()
        if progress:
            progress((i + 1) / len(paths))
    return _save(res, out)


def extract(path, ranges, out, password=None):
    src = open_pdf(path, password)
    pages = parse_ranges(ranges, src.page_count)
    src.select(pages)
    return _save(src, out)


def split(path, out_dir, mode="each", every=1, ranges="", password=None, progress=None):
    """mode: 'each' (one file per page), 'every' (chunks of N pages), 'ranges' (one file per comma part)."""
    src = open_pdf(path, password)
    n = src.page_count
    stem = os.path.splitext(os.path.basename(path))[0]
    if mode == "ranges":
        groups = [parse_ranges(part, n) for part in ranges.split(",") if part.strip()]
    else:
        size = 1 if mode == "each" else max(1, int(every))
        groups = [list(range(i, min(i + size, n))) for i in range(0, n, size)]
    os.makedirs(out_dir, exist_ok=True)
    outs = []
    for gi, g in enumerate(groups):
        part = pymupdf.open()
        for pno in g:
            part.insert_pdf(src, from_page=pno, to_page=pno)
        label = f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}-{g[-1] + 1}"
        outs.append(_save(part, unique_path(os.path.join(out_dir, f"{stem} (page {label}).pdf"
                                                         if len(g) == 1 else f"{stem} (pages {label}).pdf"))))
        if progress:
            progress((gi + 1) / len(groups))
    src.close()
    return outs


COMPRESS_LEVELS = {  # name: (images above this dpi..., ...are resampled to this dpi, jpeg quality)
    "Smallest": (100, 72, 50),
    "Balanced": (180, 150, 70),
    "High quality": (300, 220, 85),
}


def compress(path, out, level="Balanced", password=None):
    src = open_pdf(path, password)
    threshold, target, quality = COMPRESS_LEVELS.get(level, COMPRESS_LEVELS["Balanced"])
    try:
        src.rewrite_images(dpi_threshold=threshold, dpi_target=target, quality=quality,
                           lossy=True, lossless=True, bitonal=True, color=True, gray=True, set_to_gray=False)
    except Exception:
        pass  # PDFs without images, or unusual image types: just re-save compactly
    try:
        src.subset_fonts()
    except Exception:
        pass
    return _save(src, out, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True,
                 use_objstms=True)


def rotate(path, out, angle, ranges="all", password=None):
    src = open_pdf(path, password)
    for pno in parse_ranges(ranges, src.page_count):
        p = src[pno]
        p.set_rotation((p.rotation + angle) % 360)
    return _save(src, out)


def _image_doc(img_path, page_size="Fit", margin=0):
    """A one-page PDF containing the image."""
    from PIL import Image, ImageOps
    with Image.open(img_path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        buf = io.BytesIO()
        fmt = "PNG" if im.mode == "RGBA" or os.path.splitext(img_path)[1].lower() in (".png", ".gif") else "JPEG"
        if fmt == "JPEG":
            im.convert("RGB").save(buf, "JPEG", quality=92)
        else:
            im.save(buf, "PNG")
        w, h = im.size
        dpi = im.info.get("dpi", (96, 96))[0] or 96
    doc = pymupdf.open()
    if page_size in PAPER:
        r = PAPER[page_size]
        if w > h:  # landscape photos get landscape pages
            r = pymupdf.Rect(0, 0, r.height, r.width)
        page = doc.new_page(width=r.width, height=r.height)
        box = r + (margin, margin, -margin, -margin)
    else:
        pw, ph = w * 72 / max(dpi, 30), h * 72 / max(dpi, 30)
        page = doc.new_page(width=pw, height=ph)
        box = page.rect
    page.insert_image(box, stream=buf.getvalue(), keep_proportion=True)
    return doc


def images_to_pdf(paths, out, page_size="A4", progress=None):
    res = pymupdf.open()
    for i, p in enumerate(paths):
        d = _image_doc(p, page_size, margin=24 if page_size in PAPER else 0)
        res.insert_pdf(d)
        d.close()
        if progress:
            progress((i + 1) / len(paths))
    return _save(res, out)


def pdf_to_images(path, out_dir, dpi=150, fmt="png", ranges="all", password=None, progress=None):
    src = open_pdf(path, password)
    stem = os.path.splitext(os.path.basename(path))[0]
    pages = parse_ranges(ranges, src.page_count)
    os.makedirs(out_dir, exist_ok=True)
    outs = []
    for i, pno in enumerate(pages):
        pix = src[pno].get_pixmap(dpi=dpi, alpha=False)
        out = unique_path(os.path.join(out_dir, f"{stem} - page {pno + 1}.{fmt}"))
        if fmt == "jpg":
            pix.save(out, jpg_quality=90)
        else:
            pix.save(out)
        outs.append(out)
        if progress:
            progress((i + 1) / len(pages))
    src.close()
    return outs


def protect(path, out, user_pw, owner_pw=None, allow_print=True, allow_copy=False, allow_edit=False, password=None):
    src = open_pdf(path, password)
    perm = pymupdf.PDF_PERM_ACCESSIBILITY
    if allow_print:
        perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        perm |= pymupdf.PDF_PERM_COPY
    if allow_edit:
        perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ASSEMBLE
    return _save(src, out, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw,
                 owner_pw=owner_pw or user_pw, permissions=perm)


def unlock(path, out, password):
    src = open_pdf(path, password)
    return _save(src, out, encryption=pymupdf.PDF_ENCRYPT_NONE)


POSITIONS = ["Bottom center", "Bottom right", "Bottom left", "Top center", "Top right", "Top left"]


def page_numbers(path, out, position="Bottom center", start=1, template="{n} / {total}", size=10,
                 ranges="all", password=None):
    src = open_pdf(path, password)
    pages = parse_ranges(ranges, src.page_count)
    total = len(pages)
    for i, pno in enumerate(pages):
        page = src[pno]
        label = template.replace("{n}", str(start + i)).replace("{total}", str(total + start - 1))
        r = page.rect  # visible (rotated) page area
        w = pymupdf.get_text_length(label, fontname="helv", fontsize=size)
        m = 28
        x = {"left": m, "right": r.width - m - w}.get(position.split()[-1], (r.width - w) / 2)
        y = m + size if position.startswith("Top") else r.height - m
        pt = pymupdf.Point(x, y) * page.derotation_matrix
        page.insert_text(pt, label, fontsize=size, fontname="helv", color=(0.25, 0.25, 0.25),
                         rotate=page.rotation)
    return _save(src, out)


def _watermark_png(wpt, hpt, text, opacity, color, diagonal, scale=2.5):
    from PIL import Image, ImageDraw, ImageFont
    W, H = int(wpt * scale), int(hpt * scale)
    try:
        font_path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf")
        size = int(min(wpt, hpt) * scale * 0.9 / max(4, len(text)) * 1.5)
        f = ImageFont.truetype(font_path, max(12, size))
    except OSError:
        f = ImageFont.load_default()
    rgba = tuple(int(c * 255) for c in color) + (int(255 * opacity),)
    tw = int(f.getlength(text))
    layer = Image.new("RGBA", (tw + 40, int(f.size * 1.4) + 10), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((20, 0), text, font=f, fill=rgba)
    if diagonal:
        layer = layer.rotate(45, expand=True, resample=Image.BICUBIC)
    if layer.width > W or layer.height > H:  # long text on a small page: shrink to fit
        k = min(W / layer.width, H / layer.height) * 0.95
        layer = layer.resize((max(1, int(layer.width * k)), max(1, int(layer.height * k))), Image.LANCZOS)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(layer, ((W - layer.width) // 2, (H - layer.height) // 2))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def watermark(path, out, text, opacity=0.22, color=(0.8, 0.1, 0.1), diagonal=True,
              ranges="all", password=None):
    src = open_pdf(path, password)
    cache = {}
    for pno in parse_ranges(ranges, src.page_count):
        page = src[pno]
        r = page.rect  # the page as the reader sees it
        key = (round(r.width), round(r.height))
        if key not in cache:
            cache[key] = _watermark_png(r.width, r.height, text, opacity, color, diagonal)
        # Drawn as a transparent image covering the visible page: always centred, even on rotated pages.
        target = page.rect * page.derotation_matrix
        target.normalize()
        page.insert_image(target, stream=cache[key], rotate=page.rotation, keep_proportion=False, overlay=True)
    return _save(src, out)


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def info(path, password=None):
    d = open_pdf(path, password)
    res = {"pages": d.page_count, "size": os.path.getsize(path), "encrypted": d.is_encrypted}
    d.close()
    return res
