# Every English string MGR's app hands to T(): the literal first arguments of T(...) in its sources,
# plus the ones that reach T() through variables. Writes english.json (a sorted list).
import json, re, sys
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2])
files = ["mgr_menu.cpp", "mgr_quick_menu.cpp", "mgr_install.cpp", "mgr_trophies.cpp"]

lit = re.compile(r'"((?:[^"\\]|\\.)*)"')


def decode(body):
    # C escapes -> the bytes they stand for, read as UTF-8
    b = bytearray()
    i = 0
    raw = body.encode("utf-8")
    while i < len(raw):
        c = raw[i]
        if c == 0x5C:  # backslash
            n = chr(raw[i + 1])
            if n == "n": b.append(10); i += 2
            elif n == "x":
                j = i + 2
                h = b""
                while j < len(raw) and chr(raw[j]) in "0123456789abcdefABCDEF" and len(h) < 2:
                    h += bytes([raw[j]]); j += 1
                b.append(int(h, 16)); i = j
            else: b.append(raw[i + 1]); i += 2
        else:
            b.append(c); i += 1
    return b.decode("utf-8")


strings = set()
for name in files:
    text = (src / name).read_text(encoding="utf-8")
    for m in re.finditer(r"\bT\(\s*", text):
        i = m.end()
        parts = []
        # the first argument: one or more adjacent string literals
        while True:
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            lm = lit.match(text, i)
            if not lm:
                break
            parts.append(decode(lm.group(1)))
            i = lm.end()
        if parts:
            strings.add("".join(parts))

strings |= {
    # PageName
    "HOME", "CONTENT", "SAVES", "SETTINGS", "TROPHIES", "CREDITS",
    # levels, counters, the AA names that go through T()
    "LOW", "MEDIUM", "HIGH", "OFF", "SIMPLE", "DETAILED",
    # kLanguages
    "AUTO", "ENGLISH", "FRENCH", "GERMAN", "ITALIAN", "SPANISH", "PORTUGUESE",
    # the trophy grades (menu and pop-up)
    "BRONZE TROPHY", "SILVER TROPHY", "GOLD TROPHY", "PLATINUM TROPHY", "Bronze", "Silver", "Gold", "Platinum",
    # the quick menu's rows
    "CHEATS", "DISPLAY", "CONTROLLER", "Infinite Health", "Infinite Fuel Cells", "FPS Counter", "DualSense Features",
}
out.write_text(json.dumps(sorted(strings), ensure_ascii=False, indent=1), encoding="utf-8")
print(len(strings), "strings")
