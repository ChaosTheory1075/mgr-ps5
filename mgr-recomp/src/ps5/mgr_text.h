// Metal Gear Rising: Revengeance RePlatinum (PS5) - the app's own text (the menu, the quick menu,
// the installer's messages, the trophy pop-up) in the game's languages: English, Brazilian
// Portuguese, French, German, Italian or Spanish, as SETTINGS > LANGUAGE picks them (AUTO: the
// PS5's). English and Portuguese sit side by side where they're used, T("English", "Português");
// the other four are looked up by the English in mgr_text.cpp (English where one is missing).
#pragma once

#include <atomic>
#include <string>

namespace mgrps5 {

enum class Lang { kEnglish, kPortuguese, kFrench, kGerman, kItalian, kSpanish };

inline std::atomic<int> g_language{0};

// The app's text language for the Xbox 360 language the game is told (user_language).
inline void SetLanguage(int xbox) {
  Lang l = Lang::kEnglish;
  switch (xbox) {
    case 3: l = Lang::kGerman; break;
    case 4: l = Lang::kFrench; break;
    case 5: l = Lang::kSpanish; break;
    case 6: l = Lang::kItalian; break;
    case 9: l = Lang::kPortuguese; break;
  }
  g_language.store(int(l), std::memory_order_relaxed);
}
inline Lang TextLanguage() { return Lang(g_language.load(std::memory_order_relaxed)); }
inline bool Portuguese() { return TextLanguage() == Lang::kPortuguese; }

// `en` in French, German, Italian or Spanish (mgr_text.cpp); `en` itself when it has none.
const char* Translate(const char* en, Lang lang);

inline const char* T(const char* en, const char* pt) {
  const Lang l = TextLanguage();
  return l == Lang::kEnglish ? en : l == Lang::kPortuguese ? pt : Translate(en, l);
}

// Upper case in UTF-8, the accented letters too (Latin-1's: á -> Á, ç -> Ç, ü -> Ü).
inline std::string Upper(std::string s) {
  for (size_t i = 0; i < s.size(); ++i) {
    unsigned char& c = reinterpret_cast<unsigned char&>(s[i]);
    if (c >= 'a' && c <= 'z') {
      c = static_cast<unsigned char>(c - 32);
    } else if (c == 0xC3 && i + 1 < s.size()) {
      unsigned char& n = reinterpret_cast<unsigned char&>(s[i + 1]);
      if (n >= 0xA0 && n <= 0xBE && n != 0xB7) n = static_cast<unsigned char>(n - 0x20);
      ++i;
    }
  }
  return s;
}

}  // namespace mgrps5
