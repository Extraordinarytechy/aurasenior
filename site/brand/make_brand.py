"""Draw the AuraSenior logo (224x224) and banner (1440x448) used for the RCS agent profile."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
TEAL = (15, 107, 92)        # #0F6B5C, contrast about 6.4:1 on white
TEAL_DARK = (9, 72, 62)
SAFFRON = (242, 165, 65)    # #F2A541
WHITE = (255, 255, 255)


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    dirs = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"]
    for d in dirs:
        for n in names:
            p = Path(d) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def mark(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float) -> None:
    """Speech bubble with a heart: a voice companion that cares. s is the bubble width."""
    w, h = s, s * 0.74
    x0, y0 = cx - w / 2, cy - h / 2 - s * 0.06
    draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=s * 0.22, fill=WHITE)
    # tail
    tx = x0 + w * 0.26
    draw.polygon([(tx, y0 + h - 2), (tx + w * 0.2, y0 + h - 2), (tx - w * 0.04, y0 + h + s * 0.2)], fill=WHITE)
    # heart
    hr = s * 0.13
    hx, hy = cx, y0 + h * 0.46
    draw.ellipse([hx - 2 * hr, hy - hr, hx, hy + hr], fill=SAFFRON)
    draw.ellipse([hx, hy - hr, hx + 2 * hr, hy + hr], fill=SAFFRON)
    # The sides run from the bottom point to the tangent points of the two circles.
    px, py = hx, hy + hr * 2.4
    tl = _tangent(hx - hr, hy, hr, px, py, outer=-1)
    tr = _tangent(hx + hr, hy, hr, px, py, outer=1)
    draw.polygon([tl, (hx - hr, hy), (hx + hr, hy), tr, (px, py)], fill=SAFFRON)


def _tangent(cx: float, cy: float, r: float, px: float, py: float, outer: int) -> tuple[float, float]:
    """Tangent point on a circle seen from point (px, py), on the outer side (-1 left, 1 right)."""
    import math
    dx, dy = px - cx, py - cy
    d2 = dx * dx + dy * dy
    a, b = r * r / d2, r * math.sqrt(d2 - r * r) / d2
    t1 = (cx + a * dx - b * dy, cy + a * dy + b * dx)
    t2 = (cx + a * dx + b * dy, cy + a * dy - b * dx)
    return min(t1, t2) if outer < 0 else max(t1, t2)


def gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), TEAL)
    px = img.load()
    for x in range(w):
        t = x / (w - 1)
        c = tuple(int(TEAL[i] * (1 - t) + TEAL_DARK[i] * t) for i in range(3))
        for y in range(h):
            px[x, y] = c
    return img


K = 4  # draw at 4x, then downscale for smooth edges


def logo() -> None:
    img = Image.new("RGB", (224 * K, 224 * K), TEAL)
    mark(ImageDraw.Draw(img), 112 * K, 118 * K, 132 * K)
    img.resize((224, 224), Image.LANCZOS).save(OUT / "logo-224.png", optimize=True)


def banner() -> None:
    img = gradient(1440, 448).resize((1440 * K, 448 * K))
    d = ImageDraw.Draw(img)
    # Keep important content in the centre: RCS clients crop the banner edges.
    mark(d, 470 * K, 230 * K, 190 * K)
    d.text((620 * K, 150 * K), "AuraSenior", font=font(84 * K), fill=WHITE)
    d.text((624 * K, 262 * K), "A voice companion on WhatsApp", font=font(36 * K, bold=False), fill=WHITE)
    d.text((624 * K, 308 * K), "Family updates you can act on", font=font(36 * K, bold=False), fill=SAFFRON)
    img.resize((1440, 448), Image.LANCZOS).save(OUT / "banner-1440x448.png", optimize=True)


if __name__ == "__main__":
    logo()
    banner()
    for p in sorted(OUT.glob("*.png")):
        im = Image.open(p)
        print(p.name, im.size, p.stat().st_size, "bytes")
