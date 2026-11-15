"""Draws the PDFDrop icon (a document with a folded corner and a pen) with Pillow."""
from PIL import Image, ImageDraw

TOP, BOTTOM = (229, 57, 53), (183, 28, 74)
WHITE = (255, 255, 255, 255)


def make_icon(size=256):
    s = size * 4
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / s
        gd.line([(0, y), (s, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([s * .06, s * .06, s * .94, s * .94], radius=s * .22, fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # page with folded corner
    x0, y0, x1, y1, fold = s * .27, s * .20, s * .67, s * .80, s * .13
    d.polygon([(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)], fill=WHITE)
    d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(255, 205, 210, 255))
    for i, w in enumerate((.26, .22, .26, .16)):
        yy = y0 + s * (.22 + i * .09)
        d.rounded_rectangle([x0 + s * .05, yy, x0 + s * (.05 + w), yy + s * .035], radius=s * .017,
                            fill=(229, 57, 53, 200))
    # pen across the corner
    pen = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pen)
    pd.rounded_rectangle([s * .47, s * .44, s * .89, s * .54], radius=s * .05, fill=(40, 44, 60, 255))
    pd.polygon([(s * .47, s * .44), (s * .47, s * .54), (s * .38, s * .49)], fill=(255, 214, 120, 255))
    pd.polygon([(s * .40, s * .475), (s * .40, s * .505), (s * .38, s * .49)], fill=(40, 44, 60, 255))
    pen = pen.rotate(35, center=(s * .62, s * .5), resample=Image.BICUBIC)
    img.alpha_composite(pen, (int(s * .02), int(s * .1)))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "app.ico"
    make_icon(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", out)
