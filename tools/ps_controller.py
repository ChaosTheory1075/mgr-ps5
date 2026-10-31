"""PlayStation controller pictures for the game's controls pages, as texture patches.

The pause menu's, the options' and the manual's controls pages (ui_core.dtt
core.wtb texture 0, ui_option.dtt option.wtb, ui_manual.dtt manual.wtb, all
512x512 DXT5) draw an Xbox 360 pad from above and from the front (just the
pad: no callouts in the textures). Each patch here clears the pad's two areas
and draws a DualSense there, laid out as one is: the d-pad upper left, the
sticks low either side of the middle, CREATE and OPTIONS at the touchpad's top
corners, triangle, square, circle and cross where Y, X, B and A are, L1 L2 R1
R2 on the shoulders. The rest of each texture (the pages' frames) is the game's own:
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

    def smooth(path):
        """A closed path of cubic Bezier segments: (start, control 1, control 2, end), ... -> points."""
        out = []
        for p0, c1, c2, p1 in path:
            for i in range(24):
                t = i / 24
                m = 1 - t
                out.append((m ** 3 * p0[0] + 3 * m * m * t * c1[0] + 3 * m * t * t * c2[0] + t ** 3 * p1[0],
                            m ** 3 * p0[1] + 3 * m * m * t * c1[1] + 3 * m * t * t * c2[1] + t ** 3 * p1[1]))
        return out

    def mirrored(half):
        """The right half (top middle to bottom middle, clockwise) and its mirror: the whole outline."""
        return half + [(2 * CX - x, y) for x, y in reversed(half)][1:-1]

    def inset(outline, by):
        """The outline moved `by` inwards (along each point's normal)."""
        n = len(outline)
        out = []
        for i, (x, y) in enumerate(outline):
            ax, ay = outline[i - 1]
            bx, by_ = outline[(i + 1) % n]
            tx, ty = bx - ax, by_ - ay
            ln = math.hypot(tx, ty) or 1
            out.append((x - ty / ln * by, y + tx / ln * by))
        return out

    # ---- the front (in the reference's coordinates: the Xbox pad's within x 2-316, y 130-356) ----
    CX = 158.5
    half = smooth([
        ((CX, 142), (190, 142), (212, 140), (230, 135)),  # the top edge, along the touchpad
        ((230, 135), (252, 129), (278, 129), (290, 142)),  # up over the shoulder
        ((290, 142), (300, 154), (302, 180), (305, 210)),  # the grip's outside, widening as it goes down
        ((305, 210), (309, 252), (318, 300), (312, 336)),
        ((312, 336), (306, 358), (276, 360), (264, 340)),  # round the grip's end
        ((264, 340), (252, 318), (240, 290), (222, 274)),  # the grip's inside
        ((222, 274), (204, 260), (180, 258), (CX, 258)),  # the bridge between the grips
    ])
    outline = mirrored(half)
    d.polygon([B(x, y) for x, y in outline], outline=pal.outline, width=lw(3))
    d.line([B(x, y) for x, y in inset(outline, 5)] + [B(*inset(outline, 5)[0])], fill=pal.detail, width=lw(1.1),
           joint="curve")
    # the faceplate's edge: the dark middle (touchpad down to the bridge) between the white grips
    face = smooth([
        ((CX, 254), (186, 254), (210, 252), (218, 236)),
        ((218, 236), (224, 222), (214, 210), (214, 196)),
        ((214, 196), (214, 172), (226, 150), (236, 139)),
    ])
    for side in (1, -1):
        d.line([B(CX + (x - CX) * side, y) for x, y in face], fill=pal.detail, width=lw(1.1), joint="curve")
    # the touchpad, CREATE and OPTIONS at its top corners, the PS and mute buttons below it
    tp = smooth([
        ((CX, 143), (186, 143), (204, 142), (208, 146)),
        ((208, 146), (212, 152), (210, 178), (204, 192)),
        ((204, 192), (198, 202), (180, 204), (CX, 204)),
    ])
    d.polygon([B(x, y) for x, y in mirrored(tp)], outline=pal.detail, width=lw(1.4))
    for x0, ang in ((101, 60), (216, -60)):
        cx, cy = B(x0, 150)
        a = math.radians(ang)
        hx, hy = math.cos(a) * 5 * s * K, math.sin(a) * 5 * s * K
        d.line([(cx - hx, cy - hy), (cx + hx, cy + hy)], fill=pal.fill, width=lw(5))
        d.line([(cx - hx, cy - hy), (cx + hx, cy + hy)], fill=pal.detail, width=lw(2.4))
    f = font(5.5)
    for x0, label in ((101, "CREATE"), (216, "OPTIONS")):
        cx, cy = B(x0, 162)
        bb = d.textbbox((0, 0), label, font=f)
        d.text((cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]), label, font=f, fill=pal.detail)
    ps = B(CX, 218)
    circle(ps, 7 * s * K, fill=pal.button)
    text_cut(ps, "PS", 6.5)
    mx, my = B(CX, 232)
    d.rounded_rectangle([mx - 7 * s * K, my - 2.2 * s * K, mx + 7 * s * K, my + 2.2 * s * K], radius=int(2 * s * K),
                        fill=pal.fill)
    # the speaker's holes between the sticks
    for row in range(3):
        for col in range(-3, 4):
            if abs(col) == 3 and row != 1:
                continue
            circle(B(CX + col * 4.5, 240 + row * 4), 0.9 * s * K, fill=pal.detail)
    # the sticks, low and either side of the middle
    for c in ((116, 238), (201, 238)):
        cc = B(*c)
        circle(cc, 20 * s * K, outline=pal.detail, width=lw(1.4))
        circle(cc, 15 * s * K, fill=pal.fill)
        circle(cc, 9.5 * s * K, outline=pal.detail, width=lw(1.1))
    # the d-pad, upper left: four separate pointed keys
    dx, dy = B(72, 182)
    for ang in (0, 90, 180, 270):
        a = math.radians(ang)
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        key = []
        for along, side in ((5, 0), (10.5, -6.5), (22, -6.5), (23.5, -5), (23.5, 5), (22, 6.5), (10.5, 6.5)):
            key.append((dx + (ux * along + vx * side) * s * K, dy + (uy * along + vy * side) * s * K))
        d.polygon(key, fill=pal.fill, outline=pal.detail, width=lw(1))
    # the face buttons: triangle (Y), square (X), circle (B), cross (A)
    for (x, y), kind in (((245.5, 161), "triangle"), ((224.5, 182), "square"), ((266.5, 182), "circle"),
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

    # ---- the top (the Xbox pad's within x 36-282, y 2-92): the pad seen from its top edge ----
    # the top edge: wide wings at the shoulders, a dip in the middle where the touchpad is
    top_half = smooth([
        ((CX, 56), (190, 56), (212, 52), (226, 46)),  # the top edge across the touchpad
        ((226, 46), (246, 40), (268, 40), (279, 50)),  # up to the shoulder
        ((279, 50), (288, 58), (288, 76), (276, 84)),  # round the wing's end
        ((276, 84), (258, 92), (226, 90), (200, 86)),  # the front, the grips' tops
        ((200, 86), (184, 84), (172, 84), (CX, 84)),
    ])
    top_outline = [(x, y) for x, y in mirrored(top_half)]
    d.polygon([T(x, y) for x, y in top_outline], outline=pal.outline, width=lw(3))
    # the light bar strip and the USB-C port in the middle
    d.line([T(128, 70), T(189, 70)], fill=pal.fill, width=lw(2.5))
    d.rounded_rectangle([*T(151, 74), *T(166, 79)], radius=int(2.5 * s * K), outline=pal.detail, width=lw(1))
    for side in (1, -1):
        def X(x):
            return CX + (x - CX) * side
        # the trigger (L2/R2): curved, standing up behind the bumper
        trig = smooth([
            ((X(222), 46), (X(222), 26), (X(230), 6), (X(246), 4)),
            ((X(246), 4), (X(262), 3), (X(268), 20), (X(268), 42)),
        ])
        d.polygon([T(x, y) for x, y in trig + [(X(268), 46)]], fill=pal.fill)
        text_cut(T(X(245), 26), "R2" if side == 1 else "L2", 11)
        # the bumper (L1/R1): a flat key along the top edge
        bump = smooth([
            ((X(214), 51), (X(232), 44), (X(262), 41), (X(276), 50)),
            ((X(276), 50), (X(281), 54), (X(280), 61), (X(272), 62)),
            ((X(272), 62), (X(252), 60), (X(230), 61), (X(214), 63)),
            ((X(214), 63), (X(208), 61), (X(208), 53), (X(214), 51)),
        ])
        d.polygon([T(x, y) for x, y in bump], fill=pal.fill, outline=pal.detail, width=lw(1))
        text_cut(T(X(246), 55.5), "R1" if side == 1 else "L1", 9)

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
