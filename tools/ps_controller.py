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

Everything is drawn here; nothing of the game's is used. The pad's outline
and the places of its parts were measured from a 3D scan of a DualSense
(FRONT_OUTLINE, TOP_OUTLINE and the numbers in draw_pad).
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


# The DualSense, measured from a 3D scan of one (an orthographic render 1400
# pixels across 170 mm, the pad's middle at x 701): its outline from the front
# and from its top edge, and where its parts are, in that render's pixels.
FRONT_OUTLINE = [
    (184, 383), (160, 430), (136, 485), (116, 540), (97, 603), (79, 675), (62, 757), (46, 869), (41, 931), (40,
    1001), (44, 1059), (50, 1102), (55, 1124), (61, 1142), (68, 1156), (85, 1175), (100, 1187), (116, 1196), (134,
    1201), (212, 1232), (223, 1231), (230, 1225), (248, 1195), (266, 1152), (295, 1074), (334, 956), (352, 913),
    (358, 904), (379, 885), (396, 876), (412, 872), (446, 872), (535, 879), (629, 880), (867, 879), (956, 872),
    (990, 872), (1003, 875), (1013, 879), (1031, 891), (1044, 904), (1055, 923), (1076, 979), (1107, 1074), (1136,
    1152), (1159, 1205), (1176, 1229), (1182, 1232), (1190, 1232), (1268, 1201), (1286, 1196), (1311, 1180), (1332,
    1159), (1341, 1142), (1352, 1102), (1358, 1059), (1362, 1001), (1362, 953), (1358, 889), (1350, 819), (1340,
    757), (1311, 625), (1286, 540), (1266, 485), (1242, 430), (1218, 383), (1209, 373), (1196, 365), (1189, 354),
    (1180, 346), (1167, 339), (1138, 329), (1102, 321), (1071, 317), (1034, 318), (1020, 325), (999, 328), (979,
    339), (965, 338), (953, 328), (936, 323), (856, 317), (754, 313), (614, 314), (460, 324), (449, 328), (437,
    338), (423, 339), (403, 328), (382, 325), (368, 318), (331, 317), (284, 324), (235, 339), (218, 349), (213,
    354), (209, 362), (193, 373)
]
TOP_OUTLINE = [
    (40, 650), (41, 683), (48, 715), (60, 746), (76, 774), (1326, 774), (1337, 756), (1351, 724), (1359, 695),
    (1362, 674), (1360, 633), (1350, 594), (1333, 563), (1308, 535), (1279, 517), (1250, 508), (1228, 505), (1208,
    505), (1179, 508), (1159, 492), (1144, 465), (1132, 452), (1117, 441), (1098, 436), (1071, 437), (1051, 446),
    (1043, 452), (1029, 470), (1021, 495), (986, 525), (973, 534), (958, 540), (941, 544), (887, 548), (515, 548),
    (461, 544), (444, 540), (429, 534), (388, 502), (381, 495), (377, 479), (370, 465), (364, 457), (351, 446),
    (327, 436), (298, 437), (285, 441), (270, 452), (258, 465), (243, 492), (223, 508), (194, 505), (174, 505),
    (152, 508), (123, 517), (94, 535), (69, 563), (54, 589), (46, 613)
]

FRONT_BOX = (40, 313, 1362, 1232)  # the front outline's bounds
TOP_BOX = (40, 436, 1362, 774)  # the top's (cut at the face's edge)


def draw_pad(font_path, size, scale, layout, pal):
    """The pad, drawn on a transparent canvas of the texture's size times `scale`."""
    K = scale * SS
    W, H = size
    img = Image.new("RGBA", (W * K, H * K), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cut = Image.new("L", img.size, 0)
    dc = ImageDraw.Draw(cut)
    s = layout.scale

    # the scan's pixels -> the reference's coordinates (the Xbox pad's front within x 2-316, y 130-356, its top
    # within x 36-282, y 2-92) -> this canvas
    kf = min(314 / (FRONT_BOX[2] - FRONT_BOX[0]), 226 / (FRONT_BOX[3] - FRONT_BOX[1]))
    ff = (2 + (314 - (FRONT_BOX[2] - FRONT_BOX[0]) * kf) / 2, 130 + (226 - (FRONT_BOX[3] - FRONT_BOX[1]) * kf) / 2)
    kt = 246 / (TOP_BOX[2] - TOP_BOX[0])
    ft = (36, 2 + (90 - (TOP_BOX[3] - TOP_BOX[1]) * kt) / 2)

    def B(x, y):
        rx, ry = layout.body(ff[0] + (x - FRONT_BOX[0]) * kf, ff[1] + (y - FRONT_BOX[1]) * kf)
        return rx * K, ry * K

    def T(x, y):
        rx, ry = layout.top(ft[0] + (x - TOP_BOX[0]) * kt, ft[1] + (y - TOP_BOX[1]) * kt)
        return rx * K, ry * K

    def rb(r):  # a length in the front's pixels -> the canvas
        return r * kf * s * K

    def lw(px):  # a line width in the reference's units
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

    def curve(points, steps=16):
        """A smooth line through the points (Catmull-Rom)."""
        out = []
        pts = [points[0]] + list(points) + [points[-1]]
        for i in range(1, len(pts) - 2):
            p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
            for j in range(steps):
                t = j / steps
                out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t * t +
                                        (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t ** 3) for k in (0, 1)))
        out.append(points[-1])
        return out

    def rounded(points, closed=True, passes=3):
        """Corners cut (Chaikin): the scan's outline, smooth."""
        for _ in range(passes):
            out = []
            n = len(points) if closed else len(points) - 1
            for i in range(n):
                p, q = points[i], points[(i + 1) % len(points)]
                out += [(0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]),
                        (0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1])]
            points = out if closed else [points[0]] + out + [points[-1]]
        # and the scan's small wobbles averaged out
        n, k = len(points), 6
        idx = (lambda i: i % n) if closed else (lambda i: min(max(i, 0), n - 1))
        return [(sum(points[idx(i + j)][0] for j in range(-k, k + 1)) / (2 * k + 1),
                 sum(points[idx(i + j)][1] for j in range(-k, k + 1)) / (2 * k + 1)) for i in range(n)]

    def both(points):
        """The points and their mirror image (about the pad's middle)."""
        return points, [(2 * MID - x, y) for x, y in points]

    MID = 701

    # ---- the front ----
    body = [B(x, y) for x, y in rounded(FRONT_OUTLINE)]
    d.line(body + body[:2], fill=pal.outline, width=lw(3), joint="curve")
    # the faceplate's seams: from the touchpad's side round the stick and down the grip's inside
    for seam in both([(452, 330), (458, 470), (462, 560), (420, 615), (372, 690), (330, 790), (292, 900), (252, 1010),
                      (222, 1110), (206, 1205)]):
        d.line([B(x, y) for x, y in curve(seam)], fill=pal.detail, width=lw(1.1), joint="curve")
    # the touchpad
    tp = [(MID, 330), (900, 330), (946, 334), (952, 420), (944, 530), (920, 566), (MID, 572)]
    tp = tp + [(2 * MID - x, y) for x, y in reversed(tp)][1:-1]
    d.polygon([B(x, y) for x, y in rounded(tp, passes=4)], outline=pal.detail, width=lw(1.4))
    # CREATE and OPTIONS beside the touchpad's top corners
    for cx in (388, 2 * MID - 388):
        c = B(cx, 396)
        d.rounded_rectangle([c[0] - rb(13), c[1] - rb(26), c[0] + rb(13), c[1] + rb(26)], radius=int(rb(12)) - 1,
                            fill=pal.fill, outline=pal.detail, width=lw(0.9))
    # the sticks: the wells round them, their caps
    for cx in (495, 2 * MID - 495):
        circle(B(cx, 690), rb(104), outline=pal.detail, width=lw(1.1))
        circle(B(cx, 683), rb(76), fill=pal.fill)
        circle(B(cx, 683), rb(50), outline=pal.detail, width=lw(1.1))
    # the PS button, the speaker's holes above it, the mute button below
    ps = B(MID, 690)
    circle(ps, rb(24), fill=pal.button)
    text_cut(ps, "PS", 5.5)
    for row in range(3):
        for col in range(-4, 5):
            if abs(col) == 4 and row != 1:
                continue
            circle(B(MID + col * 13, 610 + row * 12), rb(3.2), fill=pal.detail)
    m = B(MID, 772)
    d.rounded_rectangle([m[0] - rb(30), m[1] - rb(8), m[0] + rb(30), m[1] + rb(8)], radius=int(rb(8)) - 1, fill=pal.fill)
    # the d-pad: four keys, rounded, narrowing to the middle
    dx, dy = 300, 525
    for ang in (0, 90, 180, 270):
        a = math.radians(ang)
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        key = [(14, 0), (34, -30), (88, -34), (112, -26), (112, 26), (88, 34), (34, 30)]
        pts = curve([(dx + ux * al + vx * sd, dy + uy * al + vy * sd) for al, sd in key + key[:1]], 6)
        d.polygon([B(x, y) for x, y in pts], fill=pal.fill, outline=pal.detail, width=lw(1))
    # the face buttons: triangle (Y), square (X), circle (B), cross (A)
    for (x, y), kind in (((1105, 435), "triangle"), ((1012, 525), "square"), ((1198, 525), "circle"),
                         ((1105, 615), "cross")):
        c = B(x, y)
        r = rb(44)
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

    # ---- the top: the pad from its top edge, the triggers standing behind the bumpers ----
    # (open where it was cut at the face's edge)
    i = max(range(len(TOP_OUTLINE)), key=lambda i: TOP_OUTLINE[i][1] < TOP_BOX[3] - 2 and TOP_OUTLINE[i - 1][1] >= TOP_BOX[3] - 2)
    top = [p for p in TOP_OUTLINE[i:] + TOP_OUTLINE[:i] if p[1] < TOP_BOX[3] - 2]
    d.line([T(x, y) for x, y in rounded(top, closed=False)], fill=pal.outline, width=lw(3), joint="curve")
    for side in (1, -1):
        def X(x):
            return MID + (x - MID) * side
        trig = curve([(X(214), 590), (X(212), 500), (X(236), 446), (X(300), 432), (X(364), 446), (X(386), 500),
                      (X(384), 590)], 8)
        d.polygon([T(x, y) for x, y in trig], fill=pal.fill)
        text_cut(T(X(300), 520), "L2" if side == 1 else "R2", 10)
        bump = curve([(X(214), 598), (X(300), 592), (X(386), 598), (X(390), 660), (X(372), 712), (X(300), 720),
                      (X(228), 712), (X(210), 660), (X(214), 598)], 8)
        d.polygon([T(x, y) for x, y in bump], fill=pal.fill, outline=pal.detail, width=lw(1))
        text_cut(T(X(300), 657), "L1" if side == 1 else "R1", 10)
    # the USB-C port, the touchpad's front edge
    u = T(MID, 647)
    rt = kt * s * K
    d.rounded_rectangle([u[0] - 30 * rt, u[1] - 8 * rt, u[0] + 30 * rt, u[1] + 8 * rt], radius=int(8 * rt) - 1,
                        outline=pal.detail, width=lw(1))
    d.line([T(x, y) for x, y in curve([(452, 708), (MID, 700), (950, 708)])], fill=pal.detail, width=lw(1.1),
           joint="curve")

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
