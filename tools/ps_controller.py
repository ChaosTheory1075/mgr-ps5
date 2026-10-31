"""PlayStation controller pictures for the game's controls pages, as texture patches.

The pause menu's, the options' and the manual's controls pages (ui_core.dtt
core.wtb texture 0, ui_option.dtt option.wtb, ui_manual.dtt manual.wtb, all
512x512 DXT5) draw an Xbox 360 pad from above and from the front, the game's
callouts pointing at its buttons. Each patch here clears the pad's two areas
and draws a PlayStation pad there - its buttons where the Xbox one's were, so
the callouts still point at them: triangle, square, circle and cross where Y,
X, B and A are, L1 L2 R1 R2 on the shoulders, CREATE and OPTIONS where BACK
and START are. The rest of each texture (the pages' frames) is the game's own:
a patch is drawn over the guest texture on the console (hd_textures.cpp,
"PTCH"), (255, 0, 255, 0) keeping the guest's texels. The HUD's Ninja Run tag
(ui_hud.dtt hud.wtb texture 0, "RT") becomes "R2" the same way.

Everything is drawn here; nothing of the game's is used.
"""
import math
import struct

from PIL import Image, ImageDraw, ImageFont

KEEP = (255, 0, 255, 0)
SS = 4  # supersampling


def write_patch_dds(path, image):
    """32-bit RGBA, one level, marked "PTCH" (hd_textures.cpp makes the mips after the merge)."""
    w, h = image.size
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x8
    pf = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    header = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, h, w, w * 4, 0, 1) + b"PTCH" + bytes(40) + pf
    header += struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    assert len(header) == 128
    with open(path, "wb") as f:
        f.write(header)
        f.write(image.convert("RGBA").tobytes())


class Layout:
    """Where a texture's pad is: its two areas (cleared), and the map from the
    core/manual pictures' coordinates (the reference) to this texture's."""

    def __init__(self, top_area, body_area, scale=1.0, body_offset=(0, 0), top_offset=(0, 0)):
        self.top_area, self.body_area = top_area, body_area
        self.scale, self.body_offset, self.top_offset = scale, body_offset, top_offset

    def body(self, x, y):
        return x * self.scale + self.body_offset[0], y * self.scale + self.body_offset[1]

    def top(self, x, y):
        return x * self.scale + self.top_offset[0], y * self.scale + self.top_offset[1]


class Palette:
    def __init__(self, outline, detail, fill, button, symbol_cut=True):
        self.outline, self.detail, self.fill, self.button = outline, detail, fill, button
        self.symbol_cut = symbol_cut


CYAN = Palette(outline=(95, 224, 255, 235), detail=(240, 240, 240, 230), fill=(95, 224, 255, 184),
               button=(202, 245, 255, 225))
TEAL = Palette(outline=(64, 160, 176, 255), detail=(240, 240, 240, 255), fill=(128, 128, 128, 255),
               button=(208, 208, 208, 255))


def draw_pad(font_path, size, scale, layout, pal):
    """The pad, drawn on a transparent canvas of the texture's size times `scale`."""
    K = scale * SS
    W, H = size
    img = Image.new("RGBA", (W * K, H * K), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cut = Image.new("L", img.size, 0)
    dc = ImageDraw.Draw(cut)
    s = layout.scale

    def P(pt):
        return (pt[0] * K, pt[1] * K)

    def B(x, y):
        return P(layout.body(x, y))

    def T(x, y):
        return P(layout.top(x, y))

    def lw(px):
        return max(1, int(px * s * K))

    def font(px):
        return ImageFont.truetype(font_path, max(1, int(px * s * K)))

    def text_cut(center, label, px):
        f = font(px)
        bb = dc.textbbox((0, 0), label, font=f)
        dc.text((center[0] - (bb[2] - bb[0]) / 2 - bb[0], center[1] - (bb[3] - bb[1]) / 2 - bb[1]), label, font=f,
                fill=255)

    def circle(c, r, **kw):
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], **kw)

    # ---- the front: the body ----
    # (a DualSense-like outline: a wide top, two grips; in the reference's coordinates)
    pts = []
    for t in range(0, 181):
        a = math.radians(t)
        pts.append((158.5 + 128 * math.cos(math.pi - a), 162 - 26 * math.sin(a)))
    right = [(286, 162), (300, 190), (312, 250), (316, 312), (306, 345), (282, 355), (262, 344), (244, 316),
             (224, 290), (200, 278), (158.5, 276)]
    left = [(2 * 158.5 - x, y) for x, y in reversed(right)]
    outline = pts + right[1:] + left[1:-1]
    body = [B(x, y) for x, y in outline]
    d.polygon(body, outline=pal.outline, width=lw(3))
    inner = [B(158.5 + (x - 158.5) * 0.95, 258 + (y - 258) * 0.93) for x, y in outline]
    d.line(inner + [inner[0]], fill=pal.detail, width=lw(1.2), joint="curve")
    # the touchpad, the light bar under it, CREATE and OPTIONS beside it, the PS button below
    d.rounded_rectangle([*B(122, 146), *B(195, 196)], radius=int(8 * s * K), outline=pal.detail, width=lw(1.5))
    for x0, label in ((127, "CREATE"), (191, "OPTIONS")):
        cx, cy = B(x0, 184)
        r = 5 * s * K
        d.rounded_rectangle([cx - r * 0.7, cy - r * 1.3, cx + r * 0.7, cy + r * 1.3], radius=int(r * 0.6),
                            fill=pal.fill, outline=pal.detail, width=lw(1))
    f = font(5.5)
    for x0, label in ((127, "CREATE"), (191, "OPTIONS")):
        cx, cy = B(x0, 172)
        bb = d.textbbox((0, 0), label, font=f)
        d.text((cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]), label, font=f, fill=pal.detail)
    ps = B(158.5, 206)
    circle(ps, 6 * s * K, fill=pal.fill, outline=pal.detail, width=lw(1))
    text_cut(ps, "PS", 6)
    # the sticks: their rings and caps (where the Xbox pad's were)
    for c in ((70, 180.5), (203, 232)):
        cc = B(*c)
        circle(cc, 21 * s * K, outline=pal.detail, width=lw(1.5))
        circle(cc, 15.5 * s * K, fill=pal.fill)
        circle(cc, 9 * s * K, outline=pal.detail, width=lw(1))
    # the d-pad: four keys pointing at its middle
    dx, dy = B(112.5, 232.5)
    for ang in (0, 90, 180, 270):
        a = math.radians(ang)
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        key = []
        for along, side in ((4, 0), (9, -7), (24, -7), (24, 7), (9, 7)):
            key.append((dx + (ux * along + vx * side) * s * K, dy + (uy * along + vy * side) * s * K))
        d.polygon(key, fill=pal.fill, outline=pal.detail, width=lw(1))
    circle((dx, dy), 26 * s * K, outline=pal.detail, width=lw(1.2))
    # the face buttons: triangle (Y), square (X), circle (B), cross (A)
    for (x, y), kind in (((245.5, 160.5), "triangle"), ((224.5, 182), "square"), ((267, 182), "circle"),
                         ((245.5, 203), "cross")):
        c = B(x, y)
        r = 10.5 * s * K
        circle(c, r, fill=pal.button)
        sym = r * 0.5
        w = lw(2.2)
        if kind == "triangle":
            p3 = [(c[0], c[1] - sym), (c[0] + sym * 0.9, c[1] + sym * 0.6), (c[0] - sym * 0.9, c[1] + sym * 0.6)]
            dc.line(p3 + [p3[0], p3[1]], fill=255, width=w, joint="curve")
        elif kind == "square":
            dc.rectangle([c[0] - sym * 0.75, c[1] - sym * 0.75, c[0] + sym * 0.75, c[1] + sym * 0.75], outline=255,
                         width=w)
        elif kind == "circle":
            dc.ellipse([c[0] - sym * 0.85, c[1] - sym * 0.85, c[0] + sym * 0.85, c[1] + sym * 0.85], outline=255,
                       width=w)
        else:
            dc.line([c[0] - sym * 0.8, c[1] - sym * 0.8, c[0] + sym * 0.8, c[1] + sym * 0.8], fill=255, width=w)
            dc.line([c[0] - sym * 0.8, c[1] + sym * 0.8, c[0] + sym * 0.8, c[1] - sym * 0.8], fill=255, width=w)

    # ---- the top: the shoulders (L2 L1 / R1 R2) and the pad's top edge ----
    top = [T(40, 88), T(40, 62), T(60, 40), T(258, 40), T(278, 62), T(278, 88)]
    d.line(top, fill=pal.outline, width=lw(3), joint="curve")
    d.line([T(130, 62), T(188, 62)], fill=pal.fill, width=lw(3))  # the light bar
    d.rounded_rectangle([*T(150, 70), *T(168, 76)], radius=int(2 * s * K), outline=pal.detail, width=lw(1))
    for x0, x1, label in ((63, 92, "L2"), (226, 255, "R2")):
        d.rounded_rectangle([*T(x0, 4), *T(x1, 48)], radius=int(12 * s * K), fill=pal.fill)
        text_cut(T((x0 + x1) / 2, 30), label, 11)
    for x0, x1, label in ((40, 88, "L1"), (230, 278, "R1")):
        d.rounded_rectangle([*T(x0, 51), *T(x1, 68)], radius=int(7 * s * K), fill=pal.fill)
        text_cut(T((x0 + x1) / 2, 59.5), label, 11)

    # the cut-outs (symbols and labels) through what's under them
    alpha = img.getchannel("A")
    alpha.paste(0, (0, 0), cut)
    img.putalpha(alpha)
    # down to `scale` (premultiplied, so transparent edges don't darken)
    return img.convert("RGBa").resize((W * scale, H * scale), Image.LANCZOS).convert("RGBA")


def controller_patch(font_path, size, scale, layout, pal):
    W, H = size
    out = Image.new("RGBA", (W * scale, H * scale), KEEP)
    pad = draw_pad(font_path, size, scale, layout, pal)
    for area in (layout.top_area, layout.body_area):
        box = tuple(v * scale for v in area)
        out.paste(pad.crop(box), box[:2])
    return out


def hud_patch(font_path, scale):
    """The HUD texture (1024x2048): its Ninja Run tag at (765, 493) - (885, 515), "RT" -> "R2"."""
    W, H = 1024, 2048
    out = Image.new("RGBA", (W * scale, H * scale), KEEP)
    area = (764, 492, 886, 516)
    K = scale * SS
    w, h = area[2] - area[0], area[3] - area[1]
    tag = Image.new("RGBA", (w * K, h * K), (0, 0, 0, 0))
    d = ImageDraw.Draw(tag)
    d.rectangle([1 * K, 1 * K, (w - 1) * K, (h - 1) * K], fill=(236, 236, 236, 235), outline=(150, 150, 150, 235),
                width=K)
    f = ImageFont.truetype(font_path, int(17 * K))
    bb = d.textbbox((0, 0), "R2", font=f)
    cut = Image.new("L", tag.size, 0)
    ImageDraw.Draw(cut).text((w * K / 2 - (bb[2] - bb[0]) / 2 - bb[0], h * K / 2 - (bb[3] - bb[1]) / 2 - bb[1]), "R2",
                             font=f, fill=255)
    alpha = tag.getchannel("A")
    alpha.paste(0, (0, 0), cut)
    tag.putalpha(alpha)
    tag = tag.convert("RGBa").resize((w * scale, h * scale), Image.LANCZOS).convert("RGBA")
    out.paste(tag, (area[0] * scale, area[1] * scale))
    return out


# the textures, by the hash of their base level as the game loads them (hd_textures.cpp)
REFERENCE = Layout(top_area=(33, 0, 286, 94), body_area=(0, 128, 319, 360))
OPTION = Layout(top_area=(70, 46, 350, 152), body_area=(32, 146, 388, 405), scale=1.113, body_offset=(33, 4.4),
                top_offset=(33, 47))
PATCHES = {
    0xEB5C9AE6D94CF776: ("core", REFERENCE, CYAN),  # ui_core.dtt core.wtb texture 0
    0xFFBBCE97298A4C4D: ("manual", REFERENCE, CYAN),  # ui_manual.dtt manual.wtb
    0x59C824A17CDB037F: ("option", OPTION, TEAL),  # ui_option.dtt option.wtb
}
HUD_HASH = 0xFC4C3072B5BCA1B3  # ui_hud.dtt hud.wtb texture 0


def write_all(font_path, out_dir, preview_dir=None):
    import os
    for h, (name, layout, pal) in PATCHES.items():
        img = controller_patch(font_path, (512, 512), 2, layout, pal)
        write_patch_dds(os.path.join(out_dir, f"{h:016x}.dds"), img)
        if preview_dir:
            shown = img.copy()
            px = shown.load()
            for y in range(shown.height):
                for x in range(shown.width):
                    if px[x, y] == KEEP:
                        px[x, y] = (80, 0, 80, 255)
            bg = Image.new("RGBA", shown.size, (30, 30, 50, 255))
            bg.alpha_composite(shown)
            bg.convert("RGB").save(os.path.join(preview_dir, f"patch_{name}.png"))
    write_patch_dds(os.path.join(out_dir, f"{HUD_HASH:016x}.dds"), hud_patch(font_path, 1))
