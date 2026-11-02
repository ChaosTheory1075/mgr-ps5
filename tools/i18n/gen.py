# Writes MGR's mgr_text.cpp (the French, German, Italian and Spanish table T() looks up) from
# tr_short.py + tr_long.py, after checking it against english.json: every string covered, none
# extra, Latin-1 letters only, the same %-formats as the English.
import json, re, sys
from pathlib import Path

here = Path(__file__).parent
sys.path.insert(0, str(here))
from tr_short import SHORT  # noqa: E402
from tr_long import LONG  # noqa: E402

english = json.loads((here / "english.json").read_text(encoding="utf-8"))
rows = SHORT + LONG
table = {}
bad = []
for r in rows:
    if len(r) != 5:
        bad.append(f"not 5 columns: {r[0][:60]!r}")
        continue
    en = r[0]
    if en in table:
        bad.append(f"twice: {en[:60]!r}")
    table[en] = r[1:]
    fmt = re.findall(r"%[a-zA-Z%]", en)
    for lang, t in zip("fr de it es".split(), r[1:]):
        if any(ord(c) > 0xFF for c in t):
            bad.append(f"{lang} not Latin-1: {t[:60]!r} {[c for c in t if ord(c) > 0xFF]}")
        if "%" in en and "%I" not in en and sorted(re.findall(r"%[sd%]", t)) != sorted(re.findall(r"%[sd%]", en)):
            bad.append(f"{lang} format differs: {t!r}")
        if en != " as " and (en.startswith(" ") != t.startswith(" ") or en.endswith(" ") != t.endswith(" ")):
            bad.append(f"{lang} edge spaces differ: {en!r} -> {t!r}")
missing = [e for e in english if e not in table]
extra = [e for e in table if e not in english]
for m in missing:
    bad.append(f"missing: {m[:80]!r}")
for e in extra:
    bad.append(f"extra: {e[:80]!r}")
if bad:
    print("\n".join(bad))
    sys.exit(1)


def c(s):
    out = []
    for ch in s:
        if ch == "\\": out.append("\\\\")
        elif ch == '"': out.append('\\"')
        elif ch == "\n": out.append("\\n")
        else: out.append(ch)
    return '"' + "".join(out) + '"'


lines = [
    "// Metal Gear Rising: Revengeance RePlatinum (PS5) - the app's text in French, German, Italian and",
    "// Spanish (mgr_text.h): looked up by the English T() is given. Made from the translations by",
    "// tools/i18n/gen.py; edit those and run it again.",
    '#include "mgr_text.h"',
    "",
    "#include <array>",
    "#include <string_view>",
    "#include <unordered_map>",
    "",
    "namespace mgrps5 {",
    "namespace {",
    "",
    "struct Row {",
    "  const char* en;",
    "  std::array<const char*, 4> text;  // French, German, Italian, Spanish",
    "};",
    "",
    "constexpr Row kRows[] = {",
]
for en in english:
    fr, de, it, es = table[en]
    lines.append(f"    {{{c(en)},")
    lines.append(f"     {{{c(fr)},")
    lines.append(f"      {c(de)},")
    lines.append(f"      {c(it)},")
    lines.append(f"      {c(es)}}}}},")
lines += [
    "};",
    "",
    "}  // namespace",
    "",
    "const char* Translate(const char* en, Lang lang) {",
    "  static const auto* const kTable = [] {",
    "    auto* t = new std::unordered_map<std::string_view, const Row*>();",
    "    for (const Row& r : kRows) (*t)[r.en] = &r;",
    "    return t;",
    "  }();",
    "  const int i = int(lang) - int(Lang::kFrench);",
    "  if (!en || i < 0 || i > 3) return en;",
    "  const auto found = kTable->find(en);",
    "  return found == kTable->end() ? en : found->second->text[size_t(i)];",
    "}",
    "",
    "}  // namespace mgrps5",
    "",
]
Path(sys.argv[1]).write_text("\n".join(lines), encoding="utf-8", newline="\n")
print(f"ok: {len(english)} strings x 4 languages -> {sys.argv[1]}")
