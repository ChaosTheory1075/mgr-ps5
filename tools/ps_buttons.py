#!/usr/bin/env python3
"""PlayStation button icons for the game's prompts, as an HD texture replacement.

    ps_buttons.py <font.ttf> <out dir>

The Xbox 360 game draws every button prompt (in the HUD, the menus, the
tutorials and the messages) from one 128x1024 DXT5 atlas: ui_core.dtt's
core.wtb, texture 1, in data000.cpk. This draws a PlayStation version of that
atlas from scratch (nothing of the game's is used): each icon at the place
and size of the one it stands for, at twice the resolution, as
<out>/<hash>.dds, which the renderer draws in its place (hd_textures.cpp).
<hash> is what the renderer computes for the original texture's base level
(XXH3-64, seeded with format 20 (DXT4_5), 128x1024, tiled): the game's file
is the same on every World disc, so it's written here.

  A, B, X, Y      -> cross, circle, square, triangle
  LB, RB, LT, RT  -> L1, R1, L2, R2
  LS, RS          -> L, R (pressed: L3, R3)
  START, BACK     -> OPTIONS, CREATE
  the d-pad       -> the four PlayStation arrows
"""
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

ATLAS_HASH = 0xB79610C556C19F60
W, H = 128, 1024  # the original's size
OUT = 2  # the replacement's scale
SS = 4  # supersampling
K = OUT * SS
WHITE = (246, 246, 246)


class Canvas:
    def __init__(self, font_path):
        self.mask = Image.new("L", (W * K, H * K), 0)
        self.font_path = font_path

    def font(self, size):
        return ImageFont.truetype(self.font_path, max(1, int(size * K)))

    def layer(self):
        return Image.new("L", self.mask.size, 0)

    def add(self, layer):
        self.mask.paste(255, (0, 0), layer)

    def cut(self, layer):
        self.mask.paste(0, (0, 0), layer)


def s(v):
    return [int(round(x * K)) for x in v]


# ---- shapes (coordinates in the original's pixels) ----

def text_layer(c, box, text, size, y_frac=0.5):
    l = c.layer()
    d = ImageDraw.Draw(l)
    f = c.font(size)
    x0, y0, w, h = box
    bb = d.textbbox((0, 0), text, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((x0 + w / 2) * K - tw / 2 - bb[0], (y0 + h * y_frac) * K - th / 2 - bb[1]), text, font=f, fill=255)
    return l


def fit_size(c, text, w, h):
    size = h
    while size > 4:
        bb = ImageDraw.Draw(c.layer()).textbbox((0, 0), text, font=c.font(size))
        if bb[2] - bb[0] <= w * K and bb[3] - bb[1] <= h * K:
            return size
        size -= 0.5
    return size


def symbol(d, kind, cx, cy, r, width, fill=255):
    """A PlayStation face symbol, its strokes `width` wide, inside radius r."""
    lw = max(1, int(width * K))
    if kind == "cross":
        a = r * 0.72
        d.line(s([cx - a, cy - a, cx + a, cy + a]), fill=fill, width=lw)
        d.line(s([cx - a, cy + a, cx + a, cy - a]), fill=fill, width=lw)
    elif kind == "circle":
        a = r * 0.72
        d.ellipse(s([cx - a, cy - a, cx + a, cy + a]), outline=fill, width=lw)
    elif kind == "square":
        a = r * 0.62
        d.rectangle(s([cx - a, cy - a, cx + a, cy + a]), outline=fill, width=lw)
    elif kind == "triangle":
        a = r * 0.82
        pts = [(cx, cy - a), (cx + a * 0.866, cy + a * 0.5), (cx - a * 0.866, cy + a * 0.5)]
        pts = [(x * K, (y + a * 0.08) * K) for x, y in pts]
        d.line(pts + [pts[0], pts[1]], fill=fill, width=lw, joint="curve")


def face(c, box, kind, style="filled"):
    """A face button: a white disc with the symbol cut out, or (outline) a ring with it drawn."""
    x0, y0, w, h = box
    r = min(w, h) / 2 - 0.5
    cx, cy = x0 + w / 2, y0 + h / 2
    l = c.layer()
    d = ImageDraw.Draw(l)
    if style == "filled":
        d.ellipse(s([cx - r, cy - r, cx + r, cy + r]), fill=255)
        c.add(l)
        cut = c.layer()
        symbol(ImageDraw.Draw(cut), kind, cx, cy, r * 0.78, r * 0.2)
        c.cut(cut)
    else:
        d.ellipse(s([cx - r, cy - r, cx + r, cy + r]), outline=255, width=max(1, int(r * 0.13 * K)))
        symbol(d, kind, cx, cy, r * 0.72, r * 0.15)
        c.add(l)


def shoulder(c, box, label, kind, style="filled"):
    """L1/R1 (a rounded tab) or L2/R2 (a trigger: round on top), the label cut out (or drawn)."""
    x0, y0, w, h = box
    l = c.layer()
    d = ImageDraw.Draw(l)
    rect = s([x0 + 0.5, y0 + 0.5, x0 + w - 0.5, y0 + h - 0.5])
    lw = max(1, int(min(w, h) * 0.08 * K))
    if kind == "trigger":
        # a rounded top, square-ish bottom
        top = h * 0.55
        if style == "filled":
            d.rounded_rectangle(rect, radius=int(top * K), fill=255)
            d.rounded_rectangle(s([x0 + 0.5, y0 + h * 0.5, x0 + w - 0.5, y0 + h - 0.5]), radius=int(h * 0.12 * K),
                                fill=255)
        else:
            d.rounded_rectangle(rect, radius=int(top * K), outline=255, width=lw)
    else:
        if style == "filled":
            d.rounded_rectangle(rect, radius=int(h * 0.32 * K), fill=255)
        else:
            d.rounded_rectangle(rect, radius=int(h * 0.32 * K), outline=255, width=lw)
    c.add(l)
    th = h * (0.62 if kind == "tab" else 0.58)
    size = fit_size(c, label, w * 0.7, th)
    t = text_layer(c, (x0, y0, w, h), label, size, 0.56 if kind == "trigger" else 0.5)
    (c.cut if style == "filled" else c.add)(t)


def stick(c, box, label, pressed=False, label_on_top=True):
    """A thumbstick from the side (cap and stem), its label above; pressed: an arrow down into the cap."""
    x0, y0, w, h = box
    lh = h * 0.42 if label_on_top else 0
    if label_on_top:
        size = fit_size(c, label, w * 0.8, lh * 0.95)
        c.add(text_layer(c, (x0, y0, w, lh), label, size))
    sy = y0 + lh + h * 0.04
    sh = y0 + h - sy
    l = c.layer()
    d = ImageDraw.Draw(l)
    cap_h = sh * 0.5
    d.rounded_rectangle(s([x0 + 0.5, sy, x0 + w - 0.5, sy + cap_h]), radius=int(cap_h * 0.5 * K), fill=255)
    d.rectangle(s([x0 + w * 0.36, sy + cap_h * 0.5, x0 + w * 0.64, y0 + h - 0.5]), fill=255)
    c.add(l)
    if pressed:
        cut = c.layer()
        ImageDraw.Draw(cut).polygon(
            [(x * K, y * K) for x, y in [(x0 + w * 0.4, sy + cap_h * 0.18), (x0 + w * 0.6, sy + cap_h * 0.18),
                                         (x0 + w * 0.5, sy + cap_h * 0.85)]], fill=255)
        c.cut(cut)
    if not label_on_top:
        size = fit_size(c, label, w * 0.5, cap_h * 0.8)
        c.cut(text_layer(c, (x0, sy, w, cap_h), label, size))


def small_stick(c, box, label, pressed):
    """The menus' small stick icons: the label cut into a wide cap."""
    x0, y0, w, h = box
    l = c.layer()
    d = ImageDraw.Draw(l)
    cap_h = h * 0.62
    d.rounded_rectangle(s([x0 + 0.5, y0 + 0.5, x0 + w - 0.5, y0 + cap_h]), radius=int(cap_h * 0.45 * K), fill=255)
    d.rectangle(s([x0 + w * 0.36, y0 + cap_h * 0.5, x0 + w * 0.64, y0 + h - 0.5]), fill=255)
    c.add(l)
    size = fit_size(c, label, w * 0.6, cap_h * 0.75)
    c.cut(text_layer(c, (x0, y0, w, cap_h), label, size))
    if pressed:
        cut = c.layer()
        ImageDraw.Draw(cut).polygon([(x * K, y * K) for x, y in [
            (x0 + w * 0.42, y0 + cap_h + h * 0.04), (x0 + w * 0.58, y0 + cap_h + h * 0.04),
            (x0 + w * 0.5, y0 + h * 0.97)]], fill=255)
        c.cut(cut)


def menu_button(c, box, label, icon):
    """OPTIONS / CREATE: a small pill with its mark, the name below."""
    x0, y0, w, h = box
    ph = h * 0.5
    pw = min(w * 0.75, ph * 1.7)
    px = x0 + (w - pw) / 2
    l = c.layer()
    d = ImageDraw.Draw(l)
    d.rounded_rectangle(s([px, y0 + 0.5, px + pw, y0 + ph]), radius=int(ph * 0.5 * K), fill=255)
    c.add(l)
    cut = c.layer()
    dc = ImageDraw.Draw(cut)
    lw = max(1, int(ph * 0.11 * K))
    cx, cy = px + pw / 2, y0 + ph / 2
    if icon == "options":  # three lines
        for k in (-1, 0, 1):
            dc.line(s([cx - pw * 0.2, cy + k * ph * 0.2, cx + pw * 0.2, cy + k * ph * 0.2]), fill=255, width=lw)
    else:  # create: three short slanted strokes
        for k in (-1, 0, 1):
            ox = k * pw * 0.13
            dc.line(s([cx + ox - ph * 0.08, cy + ph * 0.22, cx + ox + ph * 0.08, cy - ph * 0.22]), fill=255, width=lw)
    c.cut(cut)
    size = fit_size(c, label, w, h - ph - 1)
    c.add(text_layer(c, (x0, y0 + ph + 1, w, h - ph - 1), label, size))


def arrow(d, cx, cy, size, direction, fill=True, width=1.0):
    a = size / 2
    pts = {"up": [(0, -a), (a, a * 0.7), (-a, a * 0.7)], "down": [(0, a), (a, -a * 0.7), (-a, -a * 0.7)],
           "left": [(-a, 0), (a * 0.7, -a), (a * 0.7, a)], "right": [(a, 0), (-a * 0.7, -a), (-a * 0.7, a)]}[direction]
    pts = [((cx + x) * K, (cy + y) * K) for x, y in pts]
    if fill:
        d.polygon(pts, fill=255)
    else:
        d.line(pts + [pts[0], pts[1]], fill=255, width=max(1, int(width * K)), joint="curve")


def dpad(c, box, highlight=None):
    """The PlayStation d-pad: four arrow keys around a gap; one direction filled (pressed)."""
    x0, y0, w, h = box
    r = min(w, h) / 2
    cx, cy = x0 + w / 2, y0 + h / 2
    l = c.layer()
    d = ImageDraw.Draw(l)
    key = r * 0.62
    for direction, (dx, dy) in {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.items():
        kx, ky = cx + dx * r * 0.55, cy + dy * r * 0.55
        # a key: a square with its inner side pointed toward the centre
        half = key / 2
        if dx == 0:
            pts = [(kx - half, ky - dy * half), (kx + half, ky - dy * half), (kx + half, ky + dy * half * 0.2),
                   (kx, ky + dy * half), (kx - half, ky + dy * half * 0.2)]
            pts = [(x, y) for x, y in pts]
            # point toward the centre
            pts = [(kx - half, ky + dy * half), (kx + half, ky + dy * half), (kx + half, ky - dy * half * 0.15),
                   (kx, ky - dy * half * 0.95), (kx - half, ky - dy * half * 0.15)]
        else:
            pts = [(kx + dx * half, ky - half), (kx + dx * half, ky + half), (kx - dx * half * 0.15, ky + half),
                   (kx - dx * half * 0.95, ky), (kx - dx * half * 0.15, ky - half)]
        pts = [(x * K, y * K) for x, y in pts]
        if highlight == direction:
            d.polygon(pts, fill=255)
        else:
            d.line(pts + [pts[0], pts[1]], fill=255, width=max(1, int(r * 0.12 * K)), joint="curve")
    c.add(l)


def dpad_with_arrows(c, box, sides):
    """The d-pad with the directions to press beside it (left/right or up/down)."""
    x0, y0, w, h = box
    l = c.layer()
    d = ImageDraw.Draw(l)
    if sides in ("left", "right", "both"):
        a = h * 0.32
        pad = h
        px = x0 + (a + 1 if sides in ("left", "both") else 0)
        dpad(c, (px, y0, pad, h))
        if sides in ("left", "both"):
            arrow(d, x0 + a / 2, y0 + h / 2, a, "left")
        if sides in ("right", "both"):
            arrow(d, px + pad + 1 + a / 2, y0 + h / 2, a, "right")
    c.add(l)


def tri(c, box, direction, fill):
    x0, y0, w, h = box
    l = c.layer()
    arrow(ImageDraw.Draw(l), x0 + w / 2, y0 + h / 2, min(w, h) * (0.95 if fill else 0.85), direction, fill,
          width=min(w, h) * 0.12)
    c.add(l)


def plus(c, box):
    x0, y0, w, h = box
    l = c.layer()
    d = ImageDraw.Draw(l)
    t = min(w, h) * 0.28
    cx, cy = x0 + w / 2, y0 + h / 2
    d.rectangle(s([cx - w / 2 + 1, cy - t / 2, cx + w / 2 - 1, cy + t / 2]), fill=200)
    d.rectangle(s([cx - t / 2, cy - h / 2 + 1, cx + t / 2, cy + h / 2 - 1]), fill=200)
    c.add(l)


def dpad_small_arrow(c, box, direction):
    """A small d-pad with one arrow under (down) or over (up) it."""
    x0, y0, w, h = box
    ah = h * 0.28
    l = c.layer()
    d = ImageDraw.Draw(l)
    if direction == "down":
        dpad(c, (x0, y0, w, h - ah))
        arrow(d, x0 + w / 2, y0 + h - ah / 2, ah, "down")
    else:
        dpad(c, (x0, y0 + ah, w, h - ah))
        arrow(d, x0 + w / 2, y0 + ah / 2, ah, "up")
    c.add(l)


# ---- the atlas: each icon at the place of the original's (x, y, width, height) ----

def draw(c):
    # the big ones (top): triggers and bumpers, sticks, face buttons, the d-pad
    shoulder(c, (7, 7, 68, 41), "L2", "trigger")
    dpad_with_arrows(c, (87, 15, 37, 26), "left")
    shoulder(c, (7, 63, 68, 35), "R1", "tab")
    dpad_with_arrows(c, (87, 71, 37, 26), "right")
    shoulder(c, (7, 119, 68, 41), "R2", "trigger")
    dpad_with_arrows(c, (87, 127, 37, 26), "left")
    shoulder(c, (7, 175, 68, 35), "L1", "tab")
    dpad_with_arrows(c, (87, 183, 37, 26), "right")
    stick(c, (7, 233, 50, 40), "R")
    dpad_with_arrows(c, (71, 239, 47, 26), "both")
    face(c, (75, 291, 35, 35), "cross")
    stick(c, (7, 293, 50, 40), "L")
    face(c, (63, 351, 35, 35), "square")
    dpad_with_arrows(c, (3, 359, 47, 26), "both")
    face(c, (103, 405, 22, 21), "square", "outline")
    face(c, (7, 407, 35, 35), "triangle")
    dpad(c, (55, 414, 26, 27))
    tri(c, (84, 414, 12, 9), "up", True)
    tri(c, (84, 432, 12, 9), "down", True)
    face(c, (103, 461, 22, 21), "triangle", "outline")
    face(c, (7, 463, 35, 35), "circle")
    dpad(c, (55, 470, 26, 27))
    tri(c, (84, 470, 12, 9), "up", True)
    tri(c, (84, 488, 12, 9), "down", True)
    # the menus' small ones (bottom)
    shoulder(c, (4, 517, 37, 20), "R1", "tab")
    shoulder(c, (56, 517, 37, 20), "L1", "tab")
    face(c, (103, 517, 22, 21), "cross", "outline")
    shoulder(c, (3, 548, 39, 22), "R1", "tab", "outline")
    shoulder(c, (55, 548, 39, 22), "L1", "tab", "outline")
    face(c, (103, 549, 22, 21), "circle", "outline")
    tri(c, (98, 580, 27, 20), "up", False)
    shoulder(c, (4, 581, 33, 20), "R2", "tab")
    shoulder(c, (56, 581, 33, 20), "L2", "tab")
    small_stick(c, (95, 611, 30, 26), "L", False)
    shoulder(c, (3, 612, 34, 22), "R2", "tab", "outline")
    shoulder(c, (55, 612, 34, 22), "L2", "tab", "outline")
    menu_button(c, (3, 643, 33, 28), "OPTIONS", "options")
    menu_button(c, (55, 643, 33, 28), "OPTIONS", "options")
    small_stick(c, (95, 643, 30, 26), "R", False)
    small_stick(c, (4, 680, 30, 22), "L3", True)
    small_stick(c, (56, 680, 30, 22), "L", False)
    small_stick(c, (95, 680, 30, 23), "R3", True)
    menu_button(c, (95, 711, 28, 28), "CREATE", "create")
    small_stick(c, (4, 712, 30, 22), "R3", True)
    small_stick(c, (56, 712, 30, 22), "R", False)
    menu_button(c, (55, 743, 28, 28), "CREATE", "create")
    small_stick(c, (3, 744, 30, 23), "L3", True)
    dpad(c, (95, 759, 27, 26))
    plus(c, (7, 779, 20, 17))
    dpad(c, (55, 791, 27, 26))
    face(c, (95, 804, 23, 22), "triangle")
    tri(c, (2, 810, 27, 20), "down", False)
    face(c, (55, 836, 23, 22), "cross")
    face(c, (87, 836, 23, 22), "circle")
    face(c, (3, 840, 23, 22), "square")
    tri(c, (59, 869, 14, 20), "right", True)
    tri(c, (5, 870, 20, 26), "left", False)
    tri(c, (88, 872, 21, 13), "up", True)
    tri(c, (57, 898, 20, 26), "right", False)
    tri(c, (4, 909, 21, 13), "down", True)
    dpad_small_arrow(c, (87, 911, 19, 25), "down")
    tri(c, (60, 933, 14, 20), "left", True)
    dpad_small_arrow(c, (3, 946, 19, 25), "up")
    dpad_small_arrow(c, (87, 967, 19, 25), "down")
    dpad_small_arrow(c, (55, 974, 19, 25), "up")


def write_dds(path, image):
    """32-bit RGBA with its mips (tools/dds.py's layout)."""
    levels = [image]
    while levels[-1].width > 1 or levels[-1].height > 1:
        prev = levels[-1]
        levels.append(prev.resize((max(1, prev.width // 2), max(1, prev.height // 2)), Image.LANCZOS))
    w, h = image.size
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x8
    pf = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    header = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, h, w, w * 4, 0, len(levels)) + bytes(44) + pf
    header += struct.pack("<IIIII", 0x1000 | 0x400008, 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(header)
        for level in levels:
            f.write(level.convert("RGBA").tobytes())


def main():
    font, out = sys.argv[1], sys.argv[2]
    c = Canvas(font)
    draw(c)
    alpha = c.mask.resize((W * OUT, H * OUT), Image.LANCZOS)
    image = Image.new("RGBA", alpha.size, WHITE + (0,))
    image.putalpha(alpha)
    os.makedirs(out, exist_ok=True)
    write_dds(os.path.join(out, f"{ATLAS_HASH:016x}.dds"), image)
    # the controls pages' pad pictures and the HUD's Ninja Run tag (ps_controller.py)
    import ps_controller
    preview = sys.argv[3] if len(sys.argv) > 3 else None
    ps_controller.write_all(font, out, os.path.dirname(preview) if preview else None)
    if preview:
        bg = Image.new("RGBA", image.size, (30, 30, 50, 255))
        bg.alpha_composite(image)
        bg.convert("RGB").save(preview)


if __name__ == "__main__":
    main()
