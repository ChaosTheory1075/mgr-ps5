// Metal Gear Rising: Revengeance RePlatinum (PS5) - the app's own text in English or Brazilian
// Portuguese: the menu, the quick menu, the installer's messages. Portuguese while SETTINGS >
// LANGUAGE is PORTUGUESE (or AUTO on a PS5 set to Portuguese); the two side by side where they're
// used, T("English", "Português"). (The game's own text follows the same setting: its disc has pt.)
#pragma once

#include <atomic>
#include <string>

namespace mgrps5 {

inline std::atomic<bool> g_portuguese{false};

inline void SetPortuguese(bool on) { g_portuguese.store(on, std::memory_order_relaxed); }
inline bool Portuguese() { return g_portuguese.load(std::memory_order_relaxed); }
inline const char* T(const char* en, const char* pt) { return Portuguese() ? pt : en; }

// Upper case in UTF-8, the accented letters too (Latin-1's: á -> Á, ç -> Ç, õ -> Õ).
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
