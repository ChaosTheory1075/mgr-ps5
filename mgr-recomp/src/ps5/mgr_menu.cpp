// Metal Gear Rising: Revengeance RePlatinum (PS5) - the menu (see mgr_menu.h): shown before
// the game is set up (MgrApp::OnFinalizePaths, asynchronous), driven by the
// DualSense through scePad, the menu song looping under it. L1/R1 change the
// page. (Its pages and trophy list are Crackdown PS5's crackdown_menu.cpp.)
#include "mgr_menu.h"
#if REX_PLATFORM_PS5

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cfloat>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <map>
#include <set>
#include <memory>
#include <string>
#include <vector>

#include <rex/cvar.h>
#include <rex/input/sony_feedback.h>
#include <rex/logging.h>
#include <rex/ui/imgui_dialog.h>
#include <rex/ui/imgui_drawer.h>
#include <rex/ui/immediate_drawer.h>

#include "game/sound.h"
#include "imgui.h"
#include "mgr_install.h"
#include "mgr_text.h"
#include "mgr_trophies.h"
#define STB_IMAGE_STATIC
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#include "stb_image.h"

extern "C" {
int sceUserServiceInitialize(void* params);
int sceUserServiceGetInitialUser(int32_t* user_id);
int scePadInit(void);
int scePadOpen(int32_t user_id, int32_t type, int32_t index, const void* param);
int scePadGetHandle(int32_t user_id, int32_t type, int32_t index);
int scePadReadState(int32_t handle, void* data);
int sceSystemServiceParamGetInt(int param_id, int* value);
}

// The fonts, built into the app (gta4-ps5's ps5/assets/fonts: Oswald and
// Inter, SIL Open Font License).
#define MGR_INCBIN(name, file)                                                        \
  __asm__(".section .rodata\n.global " #name "\n.balign 16\n" #name ":\n.incbin \"" \
          file "\"\n.global " #name "_end\n" #name "_end:\n.byte 0\n.previous\n");    \
  extern "C" const unsigned char name[];                                              \
  extern "C" const unsigned char name##_end[];
MGR_INCBIN(mgrps5_font_title, MGRPS5_FONTS_DIR "/oswald-latin-700-normal.ttf")
MGR_INCBIN(mgrps5_font_item, MGRPS5_FONTS_DIR "/oswald-latin-600-normal.ttf")
MGR_INCBIN(mgrps5_font_body, MGRPS5_FONTS_DIR "/inter-latin-400-normal.ttf")

namespace mgrps5 {
namespace {

namespace fs = std::filesystem;

ImFont* g_title = nullptr;
ImFont* g_item = nullptr;
ImFont* g_body = nullptr;

// The menu's pictures: kept for the app's life (the frame PLAY was pressed on
// is rendered after the dialog has gone).
std::vector<std::unique_ptr<rex::ui::ImmediateTexture>>* g_textures =
    new std::vector<std::unique_ptr<rex::ui::ImmediateTexture>>();

// ---- the pad ----

enum : uint32_t {
  kUp = 1, kDown = 2, kLeft = 4, kRight = 8, kCross = 16, kCircle = 32, kL1 = 64, kR1 = 128, kTriangle = 256,
  kSquare = 512
};

constexpr uint32_t kPadUp = 0x00000010u, kPadRight = 0x00000020u, kPadDown = 0x00000040u,
                   kPadLeft = 0x00000080u, kPadL1 = 0x00000400u, kPadR1 = 0x00000800u,
                   kPadTriangle = 0x00001000u, kPadCircle = 0x00002000u, kPadCross = 0x00004000u,
                   kPadSquare = 0x00008000u;
struct PadData {
  uint32_t buttons;
  uint8_t lx, ly, rx, ry, l2, r2;
  uint16_t padding;
  uint8_t rest[240];
};

// (a handle of our own: the input driver later gets the same one)
class Pad {
 public:
  // The buttons pressed since the last read (held directions repeat).
  uint32_t Pressed() {
    if (handle_ < 0) {
      sceUserServiceInitialize(nullptr);
      scePadInit();
      int32_t user = -1;
      if (sceUserServiceGetInitialUser(&user) == 0 && user >= 0) {
        handle_ = scePadOpen(user, 0, 0, nullptr);
        if (handle_ < 0) handle_ = scePadGetHandle(user, 0, 0);
      }
      if (handle_ < 0) return 0;
    }
    PadData d{};
    if (scePadReadState(handle_, &d) != 0) return 0;
    uint32_t b = 0;
    if ((d.buttons & kPadUp) || d.ly < 64) b |= kUp;
    if ((d.buttons & kPadDown) || d.ly > 192) b |= kDown;
    if ((d.buttons & kPadLeft) || d.lx < 64) b |= kLeft;
    if ((d.buttons & kPadRight) || d.lx > 192) b |= kRight;
    if (d.buttons & kPadCross) b |= kCross;
    if (d.buttons & kPadCircle) b |= kCircle;
    if (d.buttons & kPadTriangle) b |= kTriangle;
    if (d.buttons & kPadSquare) b |= kSquare;
    if (d.buttons & kPadL1) b |= kL1;
    if (d.buttons & kPadR1) b |= kR1;
    uint32_t pressed = b & ~last_;
    const auto now = std::chrono::steady_clock::now();
    constexpr uint32_t kDirs = kUp | kDown | kLeft | kRight;
    if (b & kDirs) {
      if ((b & kDirs) != (last_ & kDirs)) {
        repeat_at_ = now + std::chrono::milliseconds(350);
      } else if (now >= repeat_at_) {
        pressed |= b & kDirs;
        repeat_at_ = now + std::chrono::milliseconds(90);
      }
    }
    last_ = b;
    // (the button that started the app is still down on the first read)
    if (first_) {
      first_ = false;
      return 0;
    }
    return pressed;
  }

 private:
  int32_t handle_ = -1;
  uint32_t last_ = 0;
  bool first_ = true;
  std::chrono::steady_clock::time_point repeat_at_{};
};

// ---- the settings (app/menu.ini: key=value lines) ----

// The game's languages (the disc has its text in these: us, fr, de, it, es, pt), as the Xbox 360 numbers them
// for XCONFIG_USER_LANGUAGE, which the game reads (sub_823247A8; sub_828CF540 maps Portuguese, 9, to its pt
// text); AUTO is the PS5's own language.
struct Language {
  const char* name;
  int xbox;  // 0: AUTO
  const char* pt;  // (its name in the menu's Portuguese)
};
constexpr Language kLanguages[] = {{"AUTO", 0, "AUTO"},          {"ENGLISH", 1, "INGLÊS"},
                                   {"FRENCH", 4, "FRANCÊS"},     {"GERMAN", 3, "ALEMÃO"},
                                   {"ITALIAN", 6, "ITALIANO"},   {"SPANISH", 5, "ESPANHOL"},
                                   {"PORTUGUESE (BR)", 9, "PORTUGUÊS (BR)"}};
constexpr int kLanguageCount = int(sizeof(kLanguages) / sizeof(kLanguages[0]));

// kLanguages' row for an Xbox 360 language number (AUTO for none of them).
int LanguageIndex(int xbox) {
  for (int i = 0; i < kLanguageCount; ++i)
    if (kLanguages[i].xbox == xbox) return i;
  return 0;
}

// The PS5's language as the Xbox 360 numbers it; English for one the game doesn't have.
// (asked once: the menu checks it every frame, and the PS5's language doesn't change while the app runs)
int SystemLanguage() {
  static const int language = [] {
    int v = 1;  // (English, US)
    if (sceSystemServiceParamGetInt(1 /* SCE_SYSTEM_SERVICE_PARAM_ID_LANG */, &v) != 0) v = 1;
    REXLOG_INFO("Metal Gear Rising: Revengeance menu: the PS5's language is {}", v);
    switch (v) {
      case 2: case 22: return 4;  // French, French (Canada)
      case 3: case 20: return 5;  // Spanish, Spanish (Latin America)
      case 4: return 3;           // German
      case 5: return 6;           // Italian
      case 7: case 17: return 9;  // Portuguese, Portuguese (Brazil)
      default: return 1;
    }
  }();
  return language;
}

struct Settings {
  int language = 0;   // kLanguages: AUTO, or the language the game is told (user_language)
  int aa = 2;         // swap_post_effect: 0 none, 1 fxaa, 2 smaa (Max Payne 3 RePrescribed's)
  bool fsr = true;    // the picture's stretch to the TV: FSR 1 (present_effect fsr) or bilinear
  int sharpness = 3;  // FSR 1's sharpening (present_fsr_sharpness_reduction): 1 low, 2 medium, 3 high
  bool host_rts = false;  // EXPERIMENTAL RENDERER: FAST (host render targets) or ACCURATE (EDRAM, fsi)
  int filter = 3;     // anisotropic_override 2..5: 2x, 4x, 8x, 16x
  bool lane = true;   // the GPU's second lane (crackdown_gpu_lane)
  int music = 60;     // the menu song's level, 0..100
  bool ps_buttons = true;      // PlayStation button icons (textures/ps: tools/ps_buttons.py)
  bool dualsense = true;       // the light bar, adaptive triggers and added rumble (mgr_game_overlay.cpp)
  int dualsense_strength = 2;  // 1..3: low, medium, high (gta4_sony_intensity)
  int fps_counter = 0;         // 0 off, 1 simple, 2 detailed (mgr_fps_counter)
  bool lightbar_effects = true;  // the light bar's flashes and pulses (mgr_lightbar_effects)
  bool skip_intro = true;        // no logos at the start (mgr_skip_intro)
  bool hd_movies = true;         // the cutscenes from movie_hd/ (mgr_hd_movies)
  bool cheat_menu = true;        // L3 + R3 opens the quick menu (mgr_cheat_menu: mgr_quick_menu.h)
  bool cheat_health = false;     // the quick menu's cheats, as it left them (mgr_cheat_health, mgr_cheat_fuel)
  bool cheat_fuel = false;
  int fov = 0;                   // FIELD OF VIEW: degrees added to the gameplay camera, 0/10/20/30 (mgr_fov_extra)

  static constexpr const char* kFilterNames[] = {"", "", "2X", "4X", "8X", "16X"};
  static constexpr const char* kAaNames[] = {"OFF", "FXAA", "SMAA"};
  static constexpr const char* kSharpnessNames[] = {"", "LOW", "MEDIUM", "HIGH"};
  // FSR 1's RCAS sharpness reduction in stops (0 = sharpest) for each sharpness.
  static constexpr const char* kSharpnessStops[] = {"", "1.0", "0.5", "0.2"};

  // The recommended settings (SQUARE on SETTINGS): the user's own, tested (2026-11-03). The menu's
  // song level stays as it is.
  static Settings Recommended(const Settings& now) {
    Settings s = now;
    s.language = LanguageIndex(0), s.aa = 2, s.fsr = true, s.sharpness = 3, s.host_rts = false, s.filter = 5;
    s.lane = true, s.ps_buttons = true, s.dualsense = true, s.dualsense_strength = 3, s.fps_counter = 0;
    s.lightbar_effects = true, s.skip_intro = true, s.hd_movies = true, s.cheat_menu = true;
    return s;
  }

  static Settings Load(const fs::path& app) {
    Settings s;
    if (std::FILE* f = std::fopen((app / "menu.ini").string().c_str(), "rb")) {
      char line[256];
      while (std::fgets(line, sizeof(line), f)) {
        char key[64] = {};
        int value = 0;
        if (std::sscanf(line, " %63[a-z_] = %d", key, &value) != 2) continue;
        const std::string k(key);
        if (k == "language") s.language = LanguageIndex(value);
        if (k == "fxaa" && value) s.aa = 1;  // (the earlier on/off row's)
        if (k == "anti_aliasing") s.aa = std::clamp(value, 0, 2);
        if (k == "upscaling_fsr") s.fsr = value != 0;
        if (k == "fsr_sharpness") s.sharpness = std::clamp(value, 1, 3);
        if (k == "renderer_fast") s.host_rts = value != 0;
        if (k == "texture_filtering") s.filter = std::clamp(value, 2, 5);
        if (k == "gpu_lane") s.lane = value != 0;
        if (k == "menu_music") s.music = std::clamp(value, 0, 100);
        if (k == "ps_buttons") s.ps_buttons = value != 0;
        if (k == "dualsense") s.dualsense = value != 0;
        if (k == "dualsense_strength") s.dualsense_strength = std::clamp(value, 1, 3);
        if (k == "fps_counter") s.fps_counter = std::clamp(value, 0, 2);
        if (k == "lightbar_effects") s.lightbar_effects = value != 0;
        if (k == "skip_intro") s.skip_intro = value != 0;
        if (k == "hd_cutscenes") s.hd_movies = value != 0;
        if (k == "cheat_menu") s.cheat_menu = value != 0;
        if (k == "cheat_health") s.cheat_health = value != 0;
        if (k == "cheat_fuel") s.cheat_fuel = value != 0;
        if (k == "field_of_view") s.fov = std::clamp(value / 10 * 10, 0, 30);
      }
      std::fclose(f);
    }
    return s;
  }

  void Save(const fs::path& app) const {
    if (std::FILE* f = std::fopen((app / "menu.ini").string().c_str(), "wb")) {
      std::fprintf(f,
                   "language = %d\nanti_aliasing = %d\nupscaling_fsr = %d\nfsr_sharpness = %d\nrenderer_fast = %d\n"
                   "texture_filtering = %d\ngpu_lane = %d\nmenu_music = %d\nps_buttons = %d\ndualsense = %d\n"
                   "dualsense_strength = %d\nfps_counter = %d\nlightbar_effects = %d\nskip_intro = %d\n"
                   "hd_cutscenes = %d\ncheat_menu = %d\ncheat_health = %d\ncheat_fuel = %d\nfield_of_view = %d\n",
                   kLanguages[language].xbox, aa, fsr ? 1 : 0, sharpness, host_rts ? 1 : 0, filter, lane ? 1 : 0,
                   music, ps_buttons ? 1 : 0, dualsense ? 1 : 0,
                   dualsense_strength, fps_counter, lightbar_effects ? 1 : 0, skip_intro ? 1 : 0,
                   hd_movies ? 1 : 0, cheat_menu ? 1 : 0, cheat_health ? 1 : 0, cheat_fuel ? 1 : 0, fov);
      std::fclose(f);
    }
  }

  // The language the game is told: the chosen one, or the PS5's for AUTO.
  int XboxLanguage() const { return kLanguages[language].xbox ? kLanguages[language].xbox : SystemLanguage(); }

  // The cvars they set, for this start.
  void Apply() const {
    // (the Xbox 360's own resolution, always: 2x cost the PS5 far more than it showed)
    rex::cvar::SetFlagByName("draw_resolution_scale_x", "1");
    rex::cvar::SetFlagByName("draw_resolution_scale_y", "1");
    // (the game paces itself to 60, as on the Xbox 360: the TV's vblanks)
    rex::cvar::SetFlagByName("vsync", "true");
    {
      // (init-only, and the start's flags are final by now; the GPU is set up after this menu)
      rex::cvar::testing::ScopedLifecycleOverride override_init_only;  // (always built, cvar.cpp)
      rex::cvar::SetFlagByName("render_target_path_vulkan", host_rts ? "fbo" : "fsi");
      // (host render targets: an unclipped draw's height from its vertices, run on the CPU - Max Payne 3
      // RePrescribed's FAST renderer lost its HDR scene and depth without it)
      rex::cvar::SetFlagByName("execute_unclipped_draw_vs_on_cpu", host_rts ? "true" : "false");
    }
    rex::cvar::SetFlagByName("swap_post_effect", aa == 2 ? "smaa" : aa == 1 ? "fxaa" : "none");
    rex::cvar::SetFlagByName("present_effect", fsr ? "fsr" : "bilinear");
    rex::cvar::SetFlagByName("present_fsr_sharpness_reduction", kSharpnessStops[sharpness]);
    rex::cvar::SetFlagByName("anisotropic_override", std::to_string(filter));
    rex::cvar::SetFlagByName("crackdown_gpu_lane", lane ? "true" : "false");
    // (the PlayStation icons are the only replacement textures: tools/ps_buttons.py)
    rex::cvar::SetFlagByName("hd_textures", ps_buttons ? "true" : "false");
    rex::cvar::SetFlagByName("hd_textures_path", "/app0/textures/ps");
    // (the DualSense: gta4-ps5's features, fed by the game's state in mgr_game_overlay.cpp; not its
    // touchpad swipes, which are GTA IV's weapon and radio controls)
    rex::input::sony::SetFeaturesEnabled(dualsense);
    rex::cvar::SetFlagByName("gta4_sony_gestures", "false");
    rex::cvar::SetFlagByName("gta4_sony_intensity",
                             dualsense_strength == 1 ? "0.3" : dualsense_strength == 3 ? "1.0" : "0.6");
    rex::cvar::SetFlagByName("mgr_fps_counter", fps_counter == 2 ? "detailed" : fps_counter == 1 ? "simple" : "off");
    rex::cvar::SetFlagByName("mgr_lightbar_effects", lightbar_effects ? "true" : "false");
    rex::cvar::SetFlagByName("mgr_skip_intro", skip_intro ? "true" : "false");
    rex::cvar::SetFlagByName("mgr_hd_movies", hd_movies ? "true" : "false");
    rex::cvar::SetFlagByName("mgr_cheat_menu", cheat_menu ? "true" : "false");
    rex::cvar::SetFlagByName("mgr_cheat_health", cheat_menu && cheat_health ? "true" : "false");
    rex::cvar::SetFlagByName("mgr_cheat_fuel", cheat_menu && cheat_fuel ? "true" : "false");
    rex::cvar::SetFlagByName("mgr_fov_extra", std::to_string(fov));
    const int xbox_language = XboxLanguage();
    rex::cvar::SetFlagByName("user_language", std::to_string(xbox_language));
    SetLanguage(xbox_language);  // (the quick menu's and the trophy pop-up's text)
    REXLOG_INFO("Metal Gear Rising: Revengeance menu: language {} (Xbox 360 language {}), cheat menu {} (health "
                "{}, fuel {}), field of view +{}", kLanguages[language].name, xbox_language,
                cheat_menu ? "on" : "off", cheat_menu && cheat_health ? "on" : "off",
                cheat_menu && cheat_fuel ? "on" : "off", fov);
    REXLOG_INFO("Metal Gear Rising: Revengeance menu: upscaling {} (sharpness {}), anti-aliasing {}, texture filtering {}, "
                "the GPU's second lane {}, renderer {}, {} button icons, DualSense features {} (strength {}), FPS counter {}",
                fsr ? "FSR 1" : "bilinear", kSharpnessNames[sharpness], kAaNames[aa], kFilterNames[filter],
                lane ? "on" : "off", host_rts ? "fast" : "accurate", ps_buttons ? "PlayStation" : "Xbox",
                dualsense ? "on" : "off", dualsense_strength, fps_counter);
  }
};

// ---- the look ----

constexpr ImU32 kWhite = IM_COL32(236, 232, 226, 255);
constexpr ImU32 kGrey = IM_COL32(150, 146, 140, 255);
constexpr ImU32 kDim = IM_COL32(90, 88, 84, 255);
constexpr ImU32 kRed = IM_COL32(196, 22, 28, 255);
constexpr ImU32 kText = IM_COL32(205, 202, 196, 255);

struct Image {
  ImTextureID id = 0;
  float w = 0, h = 0;
  explicit operator bool() const { return id != 0; }
};

float Width(ImFont* f, float size, const std::string& s) { return f->CalcTextSizeA(size, FLT_MAX, 0, s.c_str()).x; }

// `s` cut to `width` (with "..."), in whole UTF-8 letters.
std::string Fit(ImFont* f, float size, std::string s, float width) {
  if (Width(f, size, s) <= width) return s;
  while (!s.empty() && Width(f, size, s + "...") > width) {
    s.pop_back();
    while (!s.empty() && (static_cast<unsigned char>(s.back()) & 0xC0) == 0x80) s.pop_back();
  }
  return s + "...";
}

// strftime's, with %a and %b in the menu's language (the PS5's libc only has the C locale's English).
std::string Date(int64_t t, const char* format) {
  const std::time_t tt = std::time_t(t);
  const std::tm* tm = std::localtime(&tt);
  if (!tm) return {};
  std::string f = format;
  // (Portuguese, French, German, Italian, Spanish: Lang's order after English)
  static constexpr const char* kDays[5][7] = {
      {"dom", "seg", "ter", "qua", "qui", "sex", "sáb"}, {"dim", "lun", "mar", "mer", "jeu", "ven", "sam"},
      {"So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"},        {"dom", "lun", "mar", "mer", "gio", "ven", "sab"},
      {"dom", "lun", "mar", "mié", "jue", "vie", "sáb"}};
  static constexpr const char* kMonths[5][12] = {
      {"jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"},
      {"janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"},
      {"Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"},
      {"gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"},
      {"ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"}};
  if (const int l = int(TextLanguage()); l > 0) {
    for (size_t at; (at = f.find("%a")) != std::string::npos;) f.replace(at, 2, kDays[l - 1][tm->tm_wday % 7]);
    for (size_t at; (at = f.find("%b")) != std::string::npos;) f.replace(at, 2, kMonths[l - 1][tm->tm_mon % 12]);
  }
  char out[64] = {};
  std::strftime(out, sizeof(out), f.c_str(), tm);
  return out;
}

// Letter-spaced text, a whole UTF-8 letter at a time; returns its width.
float Spaced(ImDrawList* dl, ImFont* f, float size, ImVec2 p, ImU32 col, const char* t, float spacing) {
  const float x0 = p.x;
  for (const char* c = t; *c;) {
    const char* next = c + 1;
    while ((static_cast<unsigned char>(*next) & 0xC0) == 0x80) ++next;
    dl->AddText(f, size, p, col, c, next);
    p.x += f->CalcTextSizeA(size, FLT_MAX, 0, c, next).x + spacing;
    c = next;
  }
  return p.x - x0 - spacing;
}

// The footer's button hints, with SQUARE and TRIANGLE (QUADRADO, TRIÂNGULO) drawn as the DualSense's
// symbols, outlined like its buttons (X and O read as theirs already); returns the width (draw false:
// measured only).
float Hints(ImDrawList* dl, ImFont* f, float size, ImVec2 p, ImU32 col, const std::string& t, bool draw) {
  static constexpr const char* kWords[] = {"SQUARE", "QUADRADO", "TRIANGLE", "TRIÂNGULO"};
  const float x0 = p.x, icon = size * 0.66f, line = std::max(1.0f, size * 0.075f);
  size_t i = 0;
  while (i < t.size()) {
    size_t at = std::string::npos;
    int word = -1;
    for (int k = 0; k < 4; ++k) {
      const size_t a = t.find(kWords[k], i);
      if (a < at) at = a, word = k;
    }
    const size_t end = at == std::string::npos ? t.size() : at;
    if (end > i) {
      if (draw) dl->AddText(f, size, p, col, t.c_str() + i, t.c_str() + end);
      p.x += f->CalcTextSizeA(size, FLT_MAX, 0, t.c_str() + i, t.c_str() + end).x;
    }
    if (at == std::string::npos) break;
    const float cy = p.y + size * 0.52f, h = icon * 0.5f;
    if (draw && word < 2)
      dl->AddRect(ImVec2(p.x + line, cy - h + line), ImVec2(p.x + icon - line, cy + h - line), col, 0, 0, line * 1.6f);
    else if (draw)
      dl->AddTriangle(ImVec2(p.x + icon * 0.5f, cy - h), ImVec2(p.x + icon, cy + h * 0.8f), ImVec2(p.x, cy + h * 0.8f),
                      col, line * 1.6f);
    p.x += icon;
    i = at + std::char_traits<char>::length(kWords[word]);
  }
  return p.x - x0;
}

// The pages, in the tab bar's order.
enum Page { kHome, kContent, kSaves, kSettings, kTrophies, kCredits, kPages };
const char* PageName(int page) {
  static constexpr const char* kEn[kPages] = {"HOME", "CONTENT", "SAVES", "SETTINGS", "TROPHIES", "CREDITS"};
  static constexpr const char* kPt[kPages] = {"INÍCIO", "CONTEÚDO", "SAVES", "AJUSTES", "TROFÉUS", "CRÉDITOS"};
  return T(kEn[page], kPt[page]);
}

// The settings page's rows, in its order (a new option: a row here, its line
// in SettingsLines and its change in ChangeSetting).
enum SettingsRow {
  kUpscaling, kSharpness, kAntiAliasing, kFiltering, kLane, kFpsCounter, kButtons, kDualSense, kDualSenseStrength,
  kLightBar, kLanguageRow, kSkipIntro, kHdMovies, kCheatMenu, kFov, kRenderer, kMusic, kSettingsRows
};

class MenuDialog final : public rex::ui::ImGuiDialog {
 public:
  MenuDialog(rex::ui::ImGuiDrawer* drawer, rex::ui::ImmediateDrawer* immediate, const fs::path& app,
             std::function<void(MenuChoice)> play)
      : ImGuiDialog(drawer), immediate_(immediate), app_(app), play_(std::move(play)),
        settings_(Settings::Load(app)) {
    const fs::path hub = app / "hub";
    for (const char* name : {"background.jpg", "background.png"})
      if (!background_) background_ = Load(hub / name);
    logo_ = Load(hub / "logo.png");
    title_ = Load(hub / "title.png");
    std::error_code ec;
    // (an install the app was closed during: not to be taken for a finished one)
    fs::remove_all(app / "game.installing", ec);
    fs::remove_all(app / "update.installing", ec);
    for (fs::directory_iterator it(app / "dlc", ec), end; !ec && it != end; it.increment(ec))
      if (it->path().extension() == ".installing") fs::remove_all(it->path(), ec);
    ec.clear();
    Refresh();
    REXLOG_INFO("Metal Gear Rising: Revengeance menu: game {}, Title Update 4 {}, {} DLC packs, {} in install/",
                installed_.game ? "installed" : "MISSING", installed_.update ? "yes" : "NO", installed_.dlc,
                sources_.size());
    StartMusic(hub / "music");
    // (the runtime's user data: /app0/UserData/mgr)
    user_data_ = app / "UserData" / "mgr";
    TakeTrophies(trophies::Load(user_data_));
    REXLOG_INFO("Metal Gear Rising: Revengeance menu: trophies {} ({} of {} earned)", trophies_.loaded ? "listed" : "not listed yet",
                trophies_.earned, trophies_.earnable);
  }

 protected:
  void OnDraw(ImGuiIO& io) override {
    if (done_) return;
    const float dt = std::min(io.DeltaTime, 0.1f);
    time_ += dt;
    pictures_this_frame_ = 0;
    SetLanguage(settings_.XboxLanguage());  // (the menu's text follows LANGUAGE as it changes)
    HandlePad(pad_.Pressed());
    TickInstaller();
    if (music_) music_->SetVolume(leaving_ ? 0.0f : settings_.music / 100.0f);
    tab_x_ += (tab_target_x_ - tab_x_) * std::min(1.0f, dt * 14.0f);
    tab_w_ += (tab_target_w_ - tab_w_) * std::min(1.0f, dt * 14.0f);
    page_in_ = std::min(1.0f, page_in_ + dt * 5.0f);
    Draw(io.DisplaySize, dt);
    if (leaving_ && (leave_t_ += dt) > 0.7f) {
      done_ = true;
      settings_.Save(app_);
      settings_.Apply();
      Close();
      play_(MenuChoice{1});
    }
  }

 private:
  // ---- the installer (mgr_install.h) ----

  void Refresh() {
    installed_ = install::Check(app_);
    sources_ = install::Scan(app_);
    // (the HD cutscenes in movie_hd/: installed from install/ too)
    hd_movies_ = 0;
    std::error_code ec;
    for (const auto& e : fs::directory_iterator(app_ / "movie_hd", ec))
      if (e.path().extension() == ".usm" && e.file_size(ec) > 0) ++hd_movies_;
  }

  // The content rows: the game, Title Update 4, the DLC (in install::Remove's order).
  enum ContentRow { kRowGame, kRowUpdate, kRowDlc, kContentRows };

  // What waits in install/ for a content row; nullptr: nothing.
  const install::Source* SourceFor(int row) const {
    for (const auto& s : sources_) {
      const bool game = s.kind == install::Kind::kGameImage || s.kind == install::Kind::kGameFolder;
      if (row == kRowGame && game) return &s;
      if (row == kRowUpdate && s.kind == install::Kind::kUpdate && !s.installed) return &s;
      if (row == kRowDlc && s.kind == install::Kind::kDlc && !s.installed) return &s;
    }
    return nullptr;
  }
  int DlcWaiting() const {
    int n = 0;
    for (const auto& s : sources_) n += s.kind == install::Kind::kDlc && !s.installed;
    return n;
  }
  bool RowInstalled(int row) const {
    switch (row) {
      case kRowGame: return installed_.game;
      case kRowUpdate: return installed_.update;
      default: return installed_.dlc > 0;
    }
  }
  // The game and its title update: what PLAY needs.
  bool Ready() const { return installed_.game && installed_.update; }
  // The saves page's rows after BACK UP: the saves and backups to import or restore.
  std::vector<const install::Source*> SaveSources() const {
    std::vector<const install::Source*> out;
    for (const auto& s : sources_)
      if (s.kind == install::Kind::kSave || s.kind == install::Kind::kBackup) out.push_back(&s);
    return out;
  }

  // Once a frame: a finished job's outcome, and the next of what installs by itself (the game,
  // Title Update 4, the DLC), one at a time.
  void TickInstaller() {
    auto& job = install::TheJob();
    if (job.Generation() != job_generation_) {
      job_generation_ = job.Generation();
      result_t_ = time_;
      Refresh();
    }
    // (not in the first seconds: the menu on screen first, the progress with it)
    if (job.Busy() || leaving_ || time_ < 2.0f) return;
    bool started = false;
    for (const auto& s : sources_) {
      // (one installed already, in an earlier session: only to delete or keep)
      if (s.installed) {
        if (!tried_.count(s.path.string())) tried_.insert(s.path.string()), job.Leftover(s.path);
        continue;
      }
      if (!install::Automatic(s.kind) || tried_.count(s.path.string())) continue;
      if ((s.kind == install::Kind::kGameFolder || s.kind == install::Kind::kGameImage) && installed_.game) continue;
      if (s.kind == install::Kind::kUpdate && installed_.update) continue;
      tried_.insert(s.path.string());
      job.Install(app_, s);
      started = true;
      break;
    }
    // all done: delete or keep what they were installed from (after the last outcome has been read)
    if (!started && !ask_leftovers_ && !job.Leftovers().empty() && time_ - result_t_ > 2.5f) {
      ask_leftovers_ = true;
      leftover_bytes_ = job.LeftoverBytes();
    }
  }

  // A second press of the same button on the same row within 3 s: the go-ahead.
  bool Confirmed(int key) {
    if (confirm_key_ == key && time_ - confirm_t_ < 3.0f) {
      confirm_key_ = -1;
      return true;
    }
    confirm_key_ = key;
    confirm_t_ = time_;
    return false;
  }
  bool Confirming(int key) const { return confirm_key_ == key && time_ - confirm_t_ < 3.0f; }

  // ---- input ----

  void HandlePad(uint32_t p) {
    if (leaving_ || !p) return;
    if (ask_leftovers_) {
      // (the question has the pad to itself)
      if (p & kCross) install::TheJob().DeleteLeftovers(app_), ask_leftovers_ = false;
      if (p & kCircle) install::TheJob().KeepLeftovers(app_), ask_leftovers_ = false, Refresh();
      return;
    }
    if (p & (kL1 | kR1)) {
      page_ = Page((page_ + ((p & kR1) ? 1 : kPages - 1)) % kPages);
      page_in_ = 0;
      if (page_ == kSettings) in_list_ = false, confirm_key_ = -1;  // (SETTINGS opens on the game)
      return;
    }
    if ((p & kCircle) && page_ == kSettings && in_list_) {
      in_list_ = false;  // (back to the game first)
      return;
    }
    if ((p & kCircle) && page_ != kHome) {
      page_ = kHome;
      page_in_ = 0;
      return;
    }
    switch (page_) {
      case kHome:
        if ((p & kCross) && install::TheJob().Busy()) break;  // (PLAY waits for the install)
        if ((p & kCross) && !Ready()) {
          Refresh();  // (copied in since the menu opened?)
          missing_flash_ = 1.0f;
        }
        if ((p & kCross) && Ready()) {
          leaving_ = true;
          if (music_) music_->FadeOut(0.6f);
        }
        break;
      case kContent: {
        if (p & kUp) content_row_ = (content_row_ + kContentRows - 1) % kContentRows;
        if (p & kDown) content_row_ = (content_row_ + 1) % kContentRows;
        auto& job = install::TheJob();
        if (job.Busy()) break;
        if (p & kCross) {
          Refresh();
          if (const install::Source* s = SourceFor(content_row_)) job.Install(app_, *s);
        }
        if ((p & kTriangle) && RowInstalled(content_row_) && Confirmed(100 + content_row_))
          job.Uninstall(app_, install::Remove(content_row_));
        break;
      }
      case kSaves: {
        const int rows = 1 + int(SaveSources().size());
        if (p & kUp) saves_row_ = (saves_row_ + rows - 1) % rows;
        if (p & kDown) saves_row_ = (saves_row_ + 1) % rows;
        saves_row_ = std::min(saves_row_, rows - 1);
        auto& job = install::TheJob();
        if (job.Busy() || !(p & kCross)) break;
        if (saves_row_ == 0) {
          job.Backup(app_);
        } else if (Confirmed(200 + saves_row_)) {
          job.Install(app_, *SaveSources()[size_t(saves_row_ - 1)]);
        }
        break;
      }
      case kSettings: {
        // SQUARE, twice: the recommended settings back
        if ((p & kSquare) && Confirmed(300)) {
          settings_ = Settings::Recommended(settings_);
          reset_t_ = time_;
          REXLOG_INFO("Metal Gear Rising: Revengeance menu: recommended settings put back");
        }
        if (!in_list_) {
          if (p & (kRight | kCross)) in_list_ = true;  // (into its settings)
          break;
        }
        if (p & kUp) row_ = (row_ + kSettingsRows - 1) % kSettingsRows;
        if (p & kDown) row_ = (row_ + 1) % kSettingsRows;
        const int step = (p & kRight) ? 1 : (p & kLeft) ? -1 : 0;
        ChangeSetting(row_, step, (p & kCross) != 0);
        break;
      }
      case kTrophies: {
        const int n = int(items_.size());
        if (!n) break;
        if (p & kUp) trophy_ = (trophy_ + n - 1) % n;
        if (p & kDown) trophy_ = (trophy_ + 1) % n;
        if (p & kLeft) trophy_ = std::max(0, trophy_ - 8);
        if (p & kRight) trophy_ = std::min(n - 1, trophy_ + 8);
        if (p & (kUp | kDown | kLeft | kRight)) detail_in_ = 0;
        break;
      }
      default:
        break;
    }
  }

  // ---- the settings ----

  struct SettingLine {
    const char* section;  // the heading it's under
    const char* label;
    std::string value;
    bool enabled;
    const char* help;
    bool slider = false;  // (a level: the bar, not < >)
  };

  std::vector<SettingLine> SettingsLines() const {
    char music[16];
    std::snprintf(music, sizeof(music), "%d%%", settings_.music);
    const char* on = T("ON", "LIGADO");
    const char* off = T("OFF", "DESLIGADO");
    const char* graphics = T("GRAPHICS", "GRÁFICOS");
    const char* controller = T("CONTROLLER", "CONTROLE");
    const char* game = T("GAME", "JOGO");
    std::vector<SettingLine> lines(kSettingsRows);
    lines[kUpscaling] = {graphics, T("UPSCALING", "AMPLIAÇÃO"), settings_.fsr ? "FSR 1" : "BILINEAR", true,
                         T("How the picture is enlarged to your TV's resolution (up to 4K). FSR 1, AMD's upscaler, keeps "
                           "edges and detail sharp at almost no cost to the frame rate; BILINEAR is a plain, softer "
                           "stretch.",
                           "Como a imagem é ampliada para a resolução da sua TV (até 4K). O FSR 1, o ampliador da AMD, "
                           "mantém bordas e detalhes nítidos quase sem custo para a taxa de quadros; BILINEAR é uma "
                           "ampliação simples, mais suave.")};
    static constexpr const char* kSharpnessPt[] = {"", "BAIXA", "MÉDIA", "ALTA"};
    lines[kSharpness] = {graphics, T("SHARPNESS", "NITIDEZ"),
                         settings_.fsr ? T(Settings::kSharpnessNames[settings_.sharpness], kSharpnessPt[settings_.sharpness])
                                       : "-",
                         settings_.fsr,
                         T("How much FSR 1 sharpens the enlarged picture. HIGH is crispest but can make edges look "
                           "harsh; LOW is gentler.",
                           "Quanto o FSR 1 deixa a imagem ampliada mais nítida. ALTA é a mais definida, mas pode deixar "
                           "as bordas duras; BAIXA é mais suave.")};
    lines[kRenderer] = {"EXPERIMENTAL", T("RENDERER", "RENDERIZADOR"),
                        settings_.host_rts ? T("FAST", "RÁPIDO") : T("ACCURATE", "PRECISO"), true,
                        T("ACCURATE copies the Xbox 360's video memory exactly, pixel by pixel. FAST draws with the PS5's "
                          "own graphics hardware: quicker, but some effects may draw wrong. Testing: if anything looks "
                          "off, set it back to ACCURATE.",
                          "PRECISO copia a memória de vídeo do Xbox 360 exatamente, pixel por pixel. RÁPIDO desenha com "
                          "o próprio hardware gráfico do PS5: mais veloz, mas alguns efeitos podem sair errados. Em "
                          "teste: se algo parecer estranho, volte para PRECISO.")};
    auto language_name = [](int i) { return T(kLanguages[i].name, kLanguages[i].pt); };
    lines[kLanguageRow] = {game, T("LANGUAGE", "IDIOMA"),
                           settings_.language ? std::string(language_name(settings_.language))
                                              : std::string("AUTO (") +
                                                    language_name(LanguageIndex(SystemLanguage())) + ")",
                           true,
                           T("The game's text, menus and subtitles, and this menu's: English, French, German, "
                             "Italian, Spanish or Portuguese (Brazil) (the voices are English in all of them). AUTO "
                             "follows the PS5's own language, or English when the game doesn't have it. The game "
                             "takes it when you PLAY.",
                             "Os textos, menus e legendas do jogo, e os deste menu: inglês, francês, alemão, "
                             "italiano, espanhol ou português (Brasil) (as vozes são em inglês em todos). AUTO segue o "
                             "idioma do PS5, ou inglês quando o jogo não o tem. O jogo o usa quando você JOGAR.")};
    lines[kCheatMenu] = {game, T("CHEAT MENU (L3 + R3)", "TRAPAÇAS (L3 + R3)"), settings_.cheat_menu ? on : off, true,
                         T("While you play, press L3 + R3 together (both sticks in) to open the quick menu: "
                           "INFINITE HEALTH, INFINITE FUEL CELLS (Blade Mode and Ripper Mode without end), the FPS "
                           "counter and the DualSense features. O or L3 + R3 again closes it. OFF: L3 + R3 does "
                           "nothing and the cheats are off.",
                           "Durante o jogo, aperte L3 + R3 juntos (os dois analógicos) para abrir o menu rápido: "
                           "VIDA INFINITA, CÉLULAS DE ENERGIA INFINITAS (Blade Mode e Ripper Mode sem fim), o contador "
                           "de FPS e os recursos do DualSense. O ou L3 + R3 de novo fecha. DESLIGADO: L3 + R3 não faz "
                           "nada e as trapaças ficam desligadas.")};
    lines[kFov] = {game, T("FIELD OF VIEW", "CAMPO DE VISÃO"),
                   settings_.fov ? "+" + std::to_string(settings_.fov) : std::string(off), true,
                   T("Widens the camera while you play, by 10, 20 or 30 degrees, so more of the fight around "
                     "Raiden is on screen. Cutscenes keep their own framing. OFF is the Xbox 360's.",
                     "Abre a câmera enquanto você joga, em 10, 20 ou 30 graus, para mostrar mais da luta ao "
                     "redor do Raiden. As cenas mantêm o enquadramento original. DESLIGADO é o do Xbox 360.")};
    lines[kSkipIntro] = {game, T("SKIP INTRO", "PULAR INTRODUÇÃO"), settings_.skip_intro ? on : off, true,
                         T("Go straight to the title screen, without the Konami, Kojima Productions, PlatinumGames "
                           "and other logos at the start.",
                           "Vai direto para a tela de título, sem os logotipos da Konami, Kojima Productions, "
                           "PlatinumGames e outros no início.")};
    char hd[48];
    std::snprintf(hd, sizeof(hd), "%s (%d)", settings_.hd_movies ? on : off, hd_movies_);
    lines[kHdMovies] = {game, T("HD CUTSCENES", "CENAS EM HD"),
                        hd_movies_ ? std::string(hd) : std::string(T("NOT INSTALLED", "NÃO INSTALADAS")),
                        hd_movies_ > 0,
                        T("The cutscenes remastered to 1080p at 60 frames a second (MGRR FULLHD 60FPS CUTSCENE "
                          "UPSCALE on Nexus Mods), in place of the Xbox 360's 576p at 30. Put its two zips, as "
                          "downloaded, in PPSA48080/install/: they install by themselves and are deleted after "
                          "(about 21 GB). Or put the .usm files in PPSA48080/movie_hd/. The number is how many "
                          "are installed; a cutscene with none plays the disc's.",
                          "As cenas remasterizadas em 1080p a 60 quadros por segundo (MGRR FULLHD 60FPS CUTSCENE "
                          "UPSCALE, no Nexus Mods), no lugar das de 576p a 30 do Xbox 360. Coloque os dois zips, como "
                          "baixados, em PPSA48080/install/: eles se instalam sozinhos e são apagados depois (cerca de "
                          "21 GB). Ou coloque os arquivos .usm em PPSA48080/movie_hd/. O número é quantas estão "
                          "instaladas; uma cena sem a sua toca a do disco.")};
    lines[kLightBar] = {controller, T("LIGHT BAR", "BARRA DE LUZ"),
                        settings_.lightbar_effects ? T("HEALTH + EFFECTS", "VIDA + EFEITOS") : T("HEALTH ONLY", "SÓ VIDA"),
                        settings_.dualsense,
                        T("HEALTH + EFFECTS: the light bar follows Raiden's health and also flashes for hits and "
                          "repairs, pulses at low health and beats red in Ripper Mode. HEALTH ONLY: just the health, "
                          "blue to red, steady.",
                          "VIDA + EFEITOS: a barra de luz acompanha a vida do Raiden e também pisca com golpes e "
                          "reparos, pulsa com pouca vida e bate em vermelho no Ripper Mode. SÓ VIDA: apenas a vida, "
                          "de azul a vermelho, sem piscar.")};
    lines[kButtons] = {controller, T("BUTTON PROMPTS", "ÍCONES DOS BOTÕES"), settings_.ps_buttons ? "PLAYSTATION" : "XBOX",
                       true,
                       T("The buttons the game shows in its prompts, menus and tutorials: cross, circle, square and "
                         "triangle, L1 R1 L2 R2, OPTIONS, and a PlayStation pad on the controls pages - or the Xbox "
                         "360's own.",
                         "Os botões que o jogo mostra nas dicas, menus e tutoriais: xis, círculo, quadrado e "
                         "triângulo, L1 R1 L2 R2, OPTIONS e um controle de PlayStation nas telas de controles - ou os "
                         "do próprio Xbox 360.")};
    lines[kDualSense] = {controller, T("DUALSENSE FEATURES", "RECURSOS DO DUALSENSE"), settings_.dualsense ? on : off, true,
                         T("The light bar follows Raiden's health: blue when he's well, to red as it runs low, a flash "
                           "when he's hit, white as Zandatsu repairs him, deep red in Ripper Mode. L2 (Blade Mode) "
                           "pushes back while there's fuel for it, R2 (Ninja Run) gives a little, and hits rumble "
                           "harder.",
                           "A barra de luz acompanha a vida do Raiden: azul quando ele está bem, indo ao vermelho "
                           "conforme ela acaba, um clarão quando ele é atingido, branco enquanto o Zandatsu o repara, "
                           "vermelho intenso no Ripper Mode. O L2 (Blade Mode) oferece resistência enquanto há energia, "
                           "o R2 (Ninja Run) cede um pouco, e os golpes vibram mais forte.")};
    static constexpr const char* kStrengths[] = {"", "LOW", "MEDIUM", "HIGH"};
    static constexpr const char* kStrengthsPt[] = {"", "BAIXA", "MÉDIA", "ALTA"};
    lines[kDualSenseStrength] = {controller, T("FEEDBACK STRENGTH", "FORÇA DO FEEDBACK"),
                                 T(kStrengths[settings_.dualsense_strength], kStrengthsPt[settings_.dualsense_strength]),
                                 settings_.dualsense,
                                 T("How hard the adaptive triggers push back and how strong the added rumble is.",
                                   "O quanto os gatilhos adaptáveis resistem e a força da vibração extra.")};
    static constexpr const char* kCounters[] = {"OFF", "SIMPLE", "DETAILED"};
    static constexpr const char* kCountersPt[] = {"DESLIGADO", "SIMPLES", "DETALHADO"};
    lines[kFpsCounter] = {graphics, T("FPS COUNTER", "CONTADOR DE FPS"),
                          T(kCounters[settings_.fps_counter], kCountersPt[settings_.fps_counter]), true,
                          T("A frame rate counter at the left edge of the screen while you play. SIMPLE shows frames a "
                            "second and the frame time; DETAILED also the slowest frames and a graph of the last two "
                            "seconds.",
                            "Um contador de quadros no canto esquerdo da tela durante o jogo. SIMPLES mostra os quadros "
                            "por segundo e o tempo de quadro; DETALHADO também os quadros mais lentos e um gráfico dos "
                            "últimos dois segundos.")};
    lines[kAntiAliasing] = {graphics, T("ANTI-ALIASING", "ANTISSERRILHAMENTO"),
                            settings_.aa ? Settings::kAaNames[settings_.aa] : off, true,
                            T("Smooths jagged edges before the picture is enlarged. SMAA finds edges by their shape and "
                              "keeps the rest sharp; FXAA is a little cheaper but blurs fine detail. Both cost the "
                              "PS5's GPU very little.",
                              "Suaviza bordas serrilhadas antes de a imagem ser ampliada. O SMAA encontra as bordas pela "
                              "forma e mantém o resto nítido; o FXAA é um pouco mais leve, mas borra detalhes finos. "
                              "Os dois custam muito pouco à GPU do PS5.")};
    lines[kFiltering] = {graphics, T("TEXTURE FILTERING", "FILTRO DE TEXTURAS"),
                         std::string(Settings::kFilterNames[settings_.filter]) + T(" ANISOTROPIC", " ANISOTRÓPICO"),
                         true,
                         T("How sharp floors, walls and streets stay when seen at an angle. Higher is sharper; the "
                           "PS5's GPU handles 16X easily.",
                           "O quanto pisos, paredes e ruas continuam nítidos vistos de lado. Mais alto é mais nítido; "
                           "a GPU do PS5 aguenta 16X com facilidade.")};
    lines[kLane] = {graphics, T("GPU HELPER", "AUXILIAR DA GPU"), settings_.lane ? on : off, true,
                    T("A second thread that takes part of the graphics work - copying the game's memory for the GPU "
                      "and writing its texture lists - off the thread that sets the frame rate. Turn it off if "
                      "something draws wrong.",
                      "Uma segunda thread que tira parte do trabalho gráfico - copiar a memória do jogo para a GPU e "
                      "escrever as listas de texturas - da thread que define a taxa de quadros. Desligue se algo for "
                      "desenhado errado.")};
    lines[kMusic] = {T("AUDIO", "ÁUDIO"), T("MENU MUSIC", "MÚSICA DO MENU"), music, true,
                     T("How loud this menu's song is.", "O volume da música deste menu."), true};
    return lines;
  }

  void ChangeSetting(int row, int step, bool cross) {
    const bool flip = step || cross;
    switch (row) {
      case kButtons:
        if (flip) settings_.ps_buttons = !settings_.ps_buttons;
        break;
      case kLanguageRow:
        settings_.language = (settings_.language + (cross ? 1 : step) + kLanguageCount) % kLanguageCount;
        break;
      case kCheatMenu:
        if (flip) settings_.cheat_menu = !settings_.cheat_menu;
        break;
      case kSkipIntro:
        if (flip) settings_.skip_intro = !settings_.skip_intro;
        break;
      case kFov:
        if (cross) settings_.fov = settings_.fov >= 30 ? 0 : settings_.fov + 10;
        settings_.fov = std::clamp(settings_.fov + 10 * step, 0, 30);
        break;
      case kHdMovies:
        if (flip && hd_movies_) settings_.hd_movies = !settings_.hd_movies;
        break;
      case kLightBar:
        if (flip && settings_.dualsense) settings_.lightbar_effects = !settings_.lightbar_effects;
        break;
      case kDualSense:
        if (flip) settings_.dualsense = !settings_.dualsense;
        break;
      case kDualSenseStrength:
        if (!settings_.dualsense) break;
        if (cross) settings_.dualsense_strength = settings_.dualsense_strength % 3 + 1;
        settings_.dualsense_strength = std::clamp(settings_.dualsense_strength + step, 1, 3);
        break;
      case kFpsCounter:
        if (cross) settings_.fps_counter = (settings_.fps_counter + 1) % 3;
        settings_.fps_counter = std::clamp(settings_.fps_counter + step, 0, 2);
        break;
      case kUpscaling:
        if (flip) settings_.fsr = !settings_.fsr;
        break;
      case kSharpness:
        if (!settings_.fsr) break;
        if (cross) settings_.sharpness = settings_.sharpness % 3 + 1;
        settings_.sharpness = std::clamp(settings_.sharpness + step, 1, 3);
        break;
      case kAntiAliasing:
        if (cross) settings_.aa = (settings_.aa + 1) % 3;
        settings_.aa = std::clamp(settings_.aa + step, 0, 2);
        break;
      case kRenderer:
        if (flip) settings_.host_rts = !settings_.host_rts;
        break;
      case kFiltering:
        if (cross) settings_.filter = settings_.filter == 5 ? 2 : settings_.filter + 1;
        settings_.filter = std::clamp(settings_.filter + step, 2, 5);
        break;
      case kLane:
        if (flip) settings_.lane = !settings_.lane;
        break;
      case kMusic:
        settings_.music = std::clamp(settings_.music + step * 10, 0, 100);
        break;
    }
  }

  // ---- the trophies ----

  // The list's groups.
  enum Group { kEarned, kNotYet, kMultiplayer };

  // A row of the list: a trophy (its index; -1: the platinum), in its group.
  struct Item {
    int index = 0, group = 0;
  };

  void TakeTrophies(trophies::List list) {
    trophies_ = std::move(list);
    items_.clear();
    if (!trophies_.loaded) return;
    const auto& all = trophies_.trophies;
    std::vector<Item> earned, rest, online;
    for (int i = 0; i < int(all.size()); ++i) {
      const auto& t = all[size_t(i)];
      if (t.online()) online.push_back({i, kMultiplayer});
      else (t.earned ? earned : rest).push_back({i, t.earned ? kEarned : kNotYet});
    }
    std::stable_sort(earned.begin(), earned.end(), [&](const Item& a, const Item& b) {
      return all[size_t(a.index)].earned > all[size_t(b.index)].earned;
    });
    const bool plat = trophies_.Platinum();
    if (plat) items_.push_back({-1, kEarned});
    items_.insert(items_.end(), earned.begin(), earned.end());
    if (!plat) items_.push_back({-1, kNotYet});
    items_.insert(items_.end(), rest.begin(), rest.end());
    items_.insert(items_.end(), online.begin(), online.end());
  }

  bool Earned(const Item& it) const {
    return it.index < 0 ? trophies_.Platinum() : trophies_.trophies[size_t(it.index)].earned != 0;
  }
  trophies::Grade GradeOf(const Item& it) const {
    return it.index < 0 ? trophies::Grade::kPlatinum : trophies_.trophies[size_t(it.index)].grade();
  }
  std::string NameOf(const Item& it) const {
    if (it.index < 0) return T("Metal Gear Rising: Revengeance RePlatinum Platinum", "Platina de Metal Gear Rising: Revengeance RePlatinum");
    const auto& t = trophies_.trophies[size_t(it.index)];
    return (!t.earned && t.hidden()) ? T("Hidden trophy", "Troféu oculto") : t.name;
  }
  std::string TextOf(const Item& it) const {
    if (it.index < 0)
      return T("Earn every other Metal Gear Rising: Revengeance trophy (", "Conquiste todos os outros troféus de Metal Gear Rising: Revengeance (") +
             std::to_string(trophies_.earnable) + ").";
    const auto& t = trophies_.trophies[size_t(it.index)];
    std::string text;
    if (!t.earned && t.hidden()) text = T("Keep playing to find out what this one is.", "Continue jogando para descobrir qual é este.");
    else text = t.earned || t.locked_description.empty() ? t.description : t.locked_description;
    if (t.online())
      text += T("\n\nOnline: it needs a service this port can't reach, so it doesn't count toward the platinum.",
                "\n\nOnline: precisa de um serviço que este port não alcança, então não conta para a platina.");
    return text;
  }

  // A trophy's picture (the platinum's: the game's own), loaded the first time it's drawn
  // (two a frame at most, so the page doesn't hold the menu up).
  Image Picture(const Item& it) {
    const uint32_t key = it.index < 0 ? 0 : std::max(1u, trophies_.trophies[size_t(it.index)].image_id);
    if (auto found = pictures_.find(key); found != pictures_.end()) return found->second;
    if (pictures_this_frame_ >= 2) return {};
    ++pictures_this_frame_;
    const Image img = Load(it.index < 0 ? trophies::TitleIconFile(user_data_)
                                        : trophies::IconFile(user_data_, trophies_.trophies[size_t(it.index)].image_id));
    pictures_[key] = img;
    return img;
  }

  // The picture in a square: dimmed until it's earned, with a padlock; a question mark for a hidden one.
  void Icon(ImDrawList* dl, const Item& it, float x, float y, float size, float a) {
    const bool earned = Earned(it);
    const trophies::Trophy* t = it.index < 0 ? nullptr : &trophies_.trophies[size_t(it.index)];
    const float r = size * 0.08f;
    if (t && !earned && t->hidden()) {
      dl->AddRectFilled(ImVec2(x, y), ImVec2(x + size, y + size), IM_COL32(38, 36, 36, int(255 * a)), r);
      const char* q = "?";
      const float qs = size * 0.6f;
      dl->AddText(g_item, qs, ImVec2(x + (size - Width(g_item, qs, q)) * 0.5f, y + size * 0.16f),
                  IM_COL32(255, 255, 255, int(128 * a)), q);
      return;
    }
    const Image img = Picture(it);
    if (img) {
      const int tint = earned ? 255 : 90;
      dl->AddImageRounded(img.id, ImVec2(x, y), ImVec2(x + size, y + size), ImVec2(0, 0), ImVec2(1, 1),
                          IM_COL32(tint, tint, tint, int(255 * a)), r);
    } else {
      dl->AddRectFilled(ImVec2(x, y), ImVec2(x + size, y + size), IM_COL32(38, 36, 36, int(255 * a)), r);
      trophies::DrawCup(dl, ImVec2(x + size * 0.5f, y + size * 0.5f), size * 0.56f, GradeOf(it), a, earned);
    }
    if (!earned) {  // a padlock in the corner
      const float k = size / 64.0f, lx = x + size - 12 * k, ly = y + size - 12 * k;
      dl->AddCircleFilled(ImVec2(lx, ly), 12 * k, IM_COL32(0, 0, 0, int(190 * a)), 20);
      dl->AddRectFilled(ImVec2(lx - 5 * k, ly - 1.5f * k), ImVec2(lx + 5 * k, ly + 6 * k),
                        IM_COL32(230, 230, 230, int(220 * a)), 1.5f * k);
      dl->PathClear();
      dl->PathArcTo(ImVec2(lx, ly - 2 * k), 3.6f * k, 3.14159f, 6.28318f, 12);
      dl->PathStroke(IM_COL32(230, 230, 230, int(220 * a)), 0, 1.8f * k);
    }
  }

  // ---- drawing ----

  void Draw(const ImVec2& size, float dt) {
    ImDrawList* dl = ImGui::GetForegroundDrawList();
    const float u = size.y / 1080.0f;  // (laid out for 1080p, scaled to the screen)
    const float fade = leaving_ ? std::clamp(1.0f - leave_t_ / 0.6f, 0.0f, 1.0f) : std::min(time_ / 0.8f, 1.0f);
    fade_ = fade;
    u_ = u;

    DrawBackground(dl, size, dt);
    DrawTabs(dl, size);
    const float in = 1 - (1 - page_in_) * (1 - page_in_);
    page_alpha_ = fade * in;
    page_dx_ = (1 - in) * 24 * u;
    switch (page_) {
      case kHome: DrawHome(dl, size); break;
      case kContent: DrawContent(dl, size); break;
      case kSaves: DrawSaves(dl, size); break;
      case kSettings: DrawSettings(dl, size); break;
      case kTrophies: DrawTrophies(dl, size, dt); break;
      default: DrawCredits(dl, size); break;
    }
    DrawFooter(dl, size);
    if (ask_leftovers_) DrawLeftoversQuestion(dl, size);
  }

  // "The installs are done: delete the files they came from?" over the page.
  void DrawLeftoversQuestion(ImDrawList* dl, const ImVec2& size) {
    const float u = u_;
    dl->AddRectFilled(ImVec2(0, 0), size, A(IM_COL32(0, 0, 0, 170)));
    const float w = 1100 * u, x = (size.x - w) * 0.5f, y = size.y * 0.5f - 200 * u;
    dl->AddRectFilled(ImVec2(x, y), ImVec2(x + w, y + 400 * u), A(IM_COL32(14, 12, 12, 250)), 10 * u);
    dl->AddRectFilled(ImVec2(x, y), ImVec2(x + 8 * u, y + 400 * u), A(kRed));
    dl->AddText(g_item, 44 * u, ImVec2(x + 50 * u, y + 40 * u), A(kWhite), T("INSTALL COMPLETE", "INSTALAÇÃO CONCLUÍDA"));
    char line[96];
    std::snprintf(line, sizeof(line), "%.1f GB", double(leftover_bytes_) / (1024.0 * 1024.0 * 1024.0));
    const std::string text =
        std::string(T("The disc image, title update and DLC packages it was installed from are still in "
                      "PPSA48080/install/ (",
                      "A imagem do disco, a atualização e os pacotes de DLC usados na instalação ainda estão em "
                      "PPSA48080/install/ (")) +
        line +
        T("). The game doesn't need them any more.\n\nDelete them to free the space, or keep them (they won't "
          "be installed again).",
          "). O jogo não precisa mais deles.\n\nApague-os para liberar espaço, ou guarde-os (eles não serão "
          "instalados de novo).");
    dl->AddText(g_body, 28 * u, ImVec2(x + 50 * u, y + 110 * u), A(kText), text.c_str(), nullptr, w - 100 * u);
    dl->AddText(g_item, 34 * u, ImVec2(x + 50 * u, y + 320 * u), A(kWhite), T("X  DELETE", "X  APAGAR"));
    dl->AddText(g_item, 34 * u, ImVec2(x + 380 * u, y + 320 * u), A(kGrey), T("O  KEEP", "O  GUARDAR"));
  }

  ImU32 A(ImU32 c, float a = -1) const {
    if (a < 0) a = fade_;
    return (c & 0x00FFFFFFu) | (ImU32(float(c >> 24) * std::clamp(a, 0.0f, 1.0f)) << 24);
  }
  ImU32 P(ImU32 c) const { return A(c, page_alpha_); }

  // The picture covering the screen with a slow drift, darkened toward the
  // menu's side, the film's grain over it: a few flickering scratches.
  void DrawBackground(ImDrawList* dl, const ImVec2& size, float dt) {
    const float u = u_;
    dl->AddRectFilled(ImVec2(0, 0), size, IM_COL32(8, 8, 8, 255));
    if (background_) {
      const float s = std::max(size.x / background_.w, size.y / background_.h) * 1.06f;
      const float w = background_.w * s, h = background_.h * s;
      const float drift = std::sin(time_ * 0.05f) * (w - size.x) * 0.5f;
      const ImVec2 p0((size.x - w) * 0.5f + drift, (size.y - h) * 0.5f);
      dl->AddImage(background_.id, p0, ImVec2(p0.x + w, p0.y + h), ImVec2(0, 0), ImVec2(1, 1),
                   A(IM_COL32(255, 255, 255, 200)));
    }
    // the page's dark: the side of the menu on HOME, all of it on the others
    const float dark = page_ == kHome ? 0.0f : 0.74f;
    page_dark_ += (dark - page_dark_) * std::min(1.0f, dt * 6.0f);
    dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(size.x * 0.62f, size.y), A(IM_COL32(0, 0, 0, 235)),
                                A(IM_COL32(0, 0, 0, 0)), A(IM_COL32(0, 0, 0, 0)), A(IM_COL32(0, 0, 0, 235)));
    dl->AddRectFilled(ImVec2(0, 0), size, A(IM_COL32(0, 0, 0, int(255 * page_dark_))));
    // top and bottom bars' shade
    dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(size.x, 170 * u), A(IM_COL32(0, 0, 0, 200)),
                                A(IM_COL32(0, 0, 0, 200)), A(IM_COL32(0, 0, 0, 0)), A(IM_COL32(0, 0, 0, 0)));
    dl->AddRectFilledMultiColor(ImVec2(0, size.y - 150 * u), size, A(IM_COL32(0, 0, 0, 0)), A(IM_COL32(0, 0, 0, 0)),
                                A(IM_COL32(0, 0, 0, 210)), A(IM_COL32(0, 0, 0, 210)));
    // the film's grain: a few flickering scratches
    for (int i = 0; i < 6; ++i) {
      const float r = std::fmod(std::sin(float(i) * 12.9898f + std::floor(time_ * 12.0f) * 78.233f) * 43758.5453f, 1.0f);
      const float x = std::fabs(r) * size.x;
      dl->AddLine(ImVec2(x, 0), ImVec2(x + 3 * u, size.y), A(IM_COL32(255, 255, 255, 10)), 1.0f * u);
    }
  }

  void DrawTabs(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, y = 58 * u, ts = 40 * u;
    float x = 140 * u;
    // the L1 / R1 marks either side
    auto button = [&](float bx, const char* label) {
      const float bw = Width(g_body, 20 * u, label) + 18 * u;
      dl->AddRect(ImVec2(bx, y + 9 * u), ImVec2(bx + bw, y + 37 * u), A(kGrey), 6 * u, 0, 1.5f * u);
      dl->AddText(g_body, 20 * u, ImVec2(bx + 9 * u, y + 12 * u), A(kGrey), label);
      return bw;
    };
    x += button(x, "L1") + 30 * u;
    for (int i = 0; i < kPages; ++i) {
      const float w = Width(g_item, ts, PageName(i));
      if (i == page_) {
        tab_target_x_ = x, tab_target_w_ = w;
        if (tab_w_ == 0) tab_x_ = x, tab_w_ = w;
      }
      dl->AddText(g_item, ts, ImVec2(x, y), A(i == page_ ? kWhite : kGrey), PageName(i));
      x += w + 52 * u;
    }
    button(x - 22 * u, "R1");
    // the project's name at the right (hub/title.png: METAL GEAR RISING over a spaced REPLATINUM)
    if (title_) {
      const float th = 56 * u, tw = title_.w * th / title_.h;
      dl->AddImage(title_.id, ImVec2(size.x - 140 * u - tw, y - 6 * u), ImVec2(size.x - 140 * u, y - 6 * u + th),
                   ImVec2(0, 0), ImVec2(1, 1), A(kWhite));
    } else {
      const char* name = "METAL GEAR RISING  REPLATINUM";
      const float nw = Width(g_body, 20 * u, name);
      dl->AddText(g_body, 20 * u, ImVec2(size.x - 140 * u - nw, y + 12 * u), A(kDim), name);
    }
    dl->AddRectFilled(ImVec2(tab_x_, y + 56 * u), ImVec2(tab_x_ + tab_w_, y + 61 * u), A(kRed));
    dl->AddRectFilled(ImVec2(140 * u, y + 61 * u), ImVec2(size.x - 140 * u, y + 62 * u), A(IM_COL32(255, 255, 255, 40)));
  }

  void DrawFooter(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, y = size.y - 92 * u;
    std::string hints;
    switch (page_) {
      case kHome: hints = T("X  PLAY      L1 R1  PAGES", "X  JOGAR      L1 R1  PÁGINAS"); break;
      case kContent:
        hints = T("UP DOWN  MOVE      X  INSTALL      TRIANGLE  UNINSTALL      O  BACK      L1 R1  PAGES",
                  "CIMA BAIXO  MOVER      X  INSTALAR      TRIÂNGULO  DESINSTALAR      O  VOLTAR      L1 R1  PÁGINAS");
        break;
      case kSaves:
        hints = T("UP DOWN  MOVE      X  SELECT      O  BACK      L1 R1  PAGES",
                  "CIMA BAIXO  MOVER      X  ESCOLHER      O  VOLTAR      L1 R1  PÁGINAS");
        break;
      case kSettings:
        hints = in_list_ ? T("UP DOWN  MOVE      LEFT RIGHT  CHANGE      SQUARE  RECOMMENDED      O  GAME      L1 R1  PAGES", "CIMA BAIXO  MOVER      ESQUERDA DIREITA  MUDAR      QUADRADO  RECOMENDADO      O  JOGO      L1 R1  PÁGINAS")
                         : T("X  SETTINGS      SQUARE  RECOMMENDED      O  BACK      L1 R1  PAGES", "X  CONFIGURAÇÕES      QUADRADO  RECOMENDADO      O  VOLTAR      L1 R1  PÁGINAS");
        break;
      case kTrophies:
        hints = T("UP DOWN  MOVE      LEFT RIGHT  PAGE UP / DOWN      O  BACK      L1 R1  PAGES",
                  "CIMA BAIXO  MOVER      ESQUERDA DIREITA  PULAR PÁGINA      O  VOLTAR      L1 R1  PÁGINAS");
        break;
      default: hints = T("O  BACK      L1 R1  PAGES", "O  VOLTAR      L1 R1  PÁGINAS"); break;
    }
    const float hints_w = Hints(dl, g_body, 22 * u, ImVec2(0, 0), 0, hints, false);
    // HOME leaves the picture undimmed: a shade in the corner under the hints,
    // fading out to the left and upward
    const float shade = 1.0f - std::clamp(page_dark_ / 0.74f, 0.0f, 1.0f);
    if (shade > 0.01f) {
      const float xs = size.x - 140 * u - hints_w - 40 * u, ys = size.y - 150 * u, f = 160 * u;
      const ImU32 c = A(IM_COL32(0, 0, 0, int(200 * shade))), z = A(IM_COL32(0, 0, 0, 0));
      dl->AddRectFilled(ImVec2(xs, ys), size, c);
      dl->AddRectFilledMultiColor(ImVec2(xs, ys - f), ImVec2(size.x, ys), z, z, c, c);
      dl->AddRectFilledMultiColor(ImVec2(xs - f, ys), ImVec2(xs, size.y), z, c, c, z);
      dl->AddRectFilledMultiColor(ImVec2(xs - f, ys - f), ImVec2(xs, ys), z, z, c, z);
    }
    dl->AddRectFilled(ImVec2(140 * u, y - 18 * u), ImVec2(size.x - 140 * u, y - 17 * u), A(IM_COL32(255, 255, 255, 40)));
    dl->AddText(g_body, 22 * u, ImVec2(140 * u, y), A(kRed),
                Upper(Date(int64_t(std::time(nullptr)), T("%a / %b %d / %I:%M %p", "%a / %d %b / %H:%M"))).c_str());
    Hints(dl, g_body, 22 * u, ImVec2(size.x - 140 * u - hints_w, y), A(kRed), hints, true);
  }

  void DrawHome(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, left = 140 * u + page_dx_;
    float y = 250 * u;
    if (logo_) {
      const float h = 150 * u, w = logo_.w * h / logo_.h;
      dl->AddImage(logo_.id, ImVec2(left, y), ImVec2(left + w, y + h), ImVec2(0, 0), ImVec2(1, 1), P(kWhite));
      y += h + 16 * u;
    } else {
      dl->AddText(g_title, 92 * u, ImVec2(left, y), P(kWhite), "METAL GEAR");
      y += 104 * u;
      dl->AddText(g_title, 92 * u, ImVec2(left, y), P(kRed), "RISING");
      const float w = Width(g_title, 92 * u, "RISING");
      Spaced(dl, g_item, 40 * u, ImVec2(left + w + 26 * u, y + 44 * u), P(kWhite), "REVENGEANCE", 8 * u);
      y += 124 * u;
    }
    // the project's name, letter-spaced under the title
    Spaced(dl, g_item, 34 * u, ImVec2(left + 4 * u, y), P(kGrey), "REPLATINUM", 9 * u);
    y += 60 * u;
    dl->AddRectFilled(ImVec2(left, y), ImVec2(left + 90 * u, y + 5 * u), P(kRed));
    y += 44 * u;
    // PLAY, with the pulsing bar
    const float ps = 96 * u;
    const float pulse = 0.7f + 0.3f * std::sin(time_ * 5.0f);
    dl->AddRectFilled(ImVec2(left - 38 * u, y + ps * 0.2f), ImVec2(left - 24 * u, y + ps * 0.86f),
                      P((kRed & 0x00FFFFFFu) | (ImU32(255 * pulse) << 24)));
    const bool installing = install::TheJob().Busy();
    dl->AddText(g_item, ps, ImVec2(left, y), P(Ready() && !installing ? kWhite : kDim), T("PLAY", "JOGAR"));
    y += ps + 18 * u;
    if (installing) {
      y = DrawJob(dl, left, y, 900 * u) + 20 * u;
    } else if (!Ready()) {
      // what's missing, and where it goes
      missing_flash_ = std::max(0.0f, missing_flash_ - 0.03f);
      const char* what =
          !installed_.game
              ? T("THE GAME ISN'T INSTALLED\nPut your Metal Gear Rising: Revengeance disc image (.iso, any name) or "
                  "the disc's files in PPSA48080/install/ and open the app again: it installs by itself. The CONTENT "
                  "page shows what's there.",
                  "O JOGO NÃO ESTÁ INSTALADO\nColoque a imagem do disco de Metal Gear Rising: Revengeance (.iso, "
                  "qualquer nome) ou os arquivos do disco em PPSA48080/install/ e abra o app de novo: ele se instala "
                  "sozinho. A página CONTEÚDO mostra o que está lá.")
              : T("TITLE UPDATE 4 ISN'T INSTALLED\nPut Title Update 4's package (tu00000001_00000000, any name) in "
                  "PPSA48080/install/ and open the app again: it installs by itself.",
                  "A TITLE UPDATE 4 NÃO ESTÁ INSTALADA\nColoque o pacote da Title Update 4 (tu00000001_00000000, "
                  "qualquer nome) em PPSA48080/install/ e abra o app de novo: ela se instala sozinha.");
      const float pw = 900 * u, th = g_body->CalcTextSizeA(26 * u, FLT_MAX, pw, what).y;
      dl->AddRectFilled(ImVec2(left - 16 * u, y - 12 * u), ImVec2(left + pw + 16 * u, y + th + 12 * u),
                        P(IM_COL32(40, 6, 6, ImU32(200 + 55 * missing_flash_))), 6 * u);
      dl->AddRectFilled(ImVec2(left - 16 * u, y - 12 * u), ImVec2(left - 10 * u, y + th + 12 * u), P(kRed));
      dl->AddText(g_body, 26 * u, ImVec2(left, y), P(kWhite), what, nullptr, pw);
      y += th + 42 * u;
    } else {
      char where[200];
      const std::string packs = installed_.dlc == 1 ? T("1 DLC pack", "1 pacote de DLC")
                                                    : std::to_string(installed_.dlc) + T(" DLC packs", " pacotes de DLC");
      std::snprintf(where, sizeof(where),
                    T("Title Update 4, %s and your saves load with the game.",
                      "A Title Update 4, %s e seus saves carregam com o jogo."),
                    packs.c_str());
      dl->AddText(g_body, 26 * u, ImVec2(left, y), P(kGrey), where);
      y += 54 * u;
    }
    if (trophies_.loaded) {
      // (on a dark panel: the picture behind it is busy)
      dl->AddRectFilled(ImVec2(left - 16 * u, y - 12 * u), ImVec2(left + 560 * u, y + 48 * u),
                        P(IM_COL32(8, 8, 8, 185)), 6 * u);
      dl->AddRectFilled(ImVec2(left - 16 * u, y - 12 * u), ImVec2(left - 11 * u, y + 48 * u), P(kRed));
      trophies::DrawCup(dl, ImVec2(left + 14 * u, y + 16 * u), 30 * u,
                        trophies_.Platinum() ? trophies::Grade::kPlatinum : trophies::Grade::kGold, page_alpha_,
                        trophies_.earned > 0);
      char line[96];
      std::snprintf(line, sizeof(line), T("%d of %d trophies  -  %d%%", "%d de %d troféus  -  %d%%"), trophies_.earned,
                    trophies_.earnable, trophies_.Percent());
      dl->AddText(g_body, 26 * u, ImVec2(left + 40 * u, y), P(kWhite), line);
    }
  }

  // The running job's title and progress bar, or the last one's outcome for a while; the y under it.
  float DrawJob(ImDrawList* dl, float x, float y, float w) {
    const float u = u_;
    auto& job = install::TheJob();
    if (job.Busy()) {
      const float pr = job.Progress();
      char line[64];
      std::snprintf(line, sizeof(line), "%d%%", int(pr * 100));
      dl->AddRectFilled(ImVec2(x - 16 * u, y - 12 * u), ImVec2(x + w + 16 * u, y + 78 * u), P(IM_COL32(8, 8, 8, 200)),
                        6 * u);
      // (a long disc image name cut short of the percentage)
      const float pw = Width(g_body, 26 * u, line);
      dl->AddText(g_body, 26 * u, ImVec2(x, y), P(kWhite),
                  Fit(g_body, 26 * u, Upper(job.Title()), w - pw - 30 * u).c_str());
      dl->AddText(g_body, 26 * u, ImVec2(x + w - pw, y), P(kRed), line);
      dl->AddRectFilled(ImVec2(x, y + 46 * u), ImVec2(x + w, y + 54 * u), P(kDim));
      dl->AddRectFilled(ImVec2(x, y + 46 * u), ImVec2(x + w * pr, y + 54 * u), P(kRed));
      return y + 90 * u;
    }
    const std::string result = job.Result();
    if (!result.empty() && time_ - result_t_ < 12.0f) {
      const float th = g_body->CalcTextSizeA(26 * u, FLT_MAX, w, result.c_str()).y;
      dl->AddRectFilled(ImVec2(x - 16 * u, y - 12 * u), ImVec2(x + w + 16 * u, y + th + 12 * u),
                        P(IM_COL32(8, 8, 8, 200)), 6 * u);
      dl->AddRectFilled(ImVec2(x - 16 * u, y - 12 * u), ImVec2(x - 10 * u, y + th + 12 * u),
                        P(job.Failed() ? IM_COL32(230, 50, 40, 255) : kWhite));
      dl->AddText(g_body, 26 * u, ImVec2(x, y), P(kWhite), result.c_str(), nullptr, w);
      return y + th + 30 * u;
    }
    return y;
  }

  static std::string Short(std::string s, size_t n) {
    if (s.size() > n) s = s.substr(0, n - 3) + "...";
    return s;
  }

  void DrawContent(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, left = 140 * u + page_dx_;
    float y = 200 * u;
    const std::string dlc_name =
        installed_.dlc ? "DLC  (" + std::to_string(installed_.dlc) +
                             (installed_.dlc == 1 ? T(" PACK)", " PACOTE)") : T(" PACKS)", " PACOTES)"))
                       : "DLC";
    const std::string names[kContentRows] = {T("GAME", "JOGO"), "TITLE UPDATE 4", dlc_name};
    const char* help[kContentRows] = {
        T("Metal Gear Rising: Revengeance's disc. Put your disc image (.iso, any name) or a folder of the disc's files "
          "in PPSA48080/install/: it installs into PPSA48080/game/ when the app opens, or with X here.",
          "O disco de Metal Gear Rising: Revengeance. Coloque a imagem do disco (.iso, qualquer nome) ou uma pasta com "
          "os arquivos do disco em PPSA48080/install/: ele se instala em PPSA48080/game/ quando o app abre, ou com X "
          "aqui."),
        T("Required: the game runs Title Update 4's code. Put its package (tu00000001_00000000, any name) in "
          "PPSA48080/install/. Other title updates can't be used.",
          "Obrigatória: o jogo roda o código da Title Update 4. Coloque o pacote dela (tu00000001_00000000, qualquer "
          "nome) em PPSA48080/install/. Outras atualizações não servem."),
        T("Optional: the DLC (Jetstream, Blade Wolf, the VR missions, the costumes). Put their packages (any names) "
          "in PPSA48080/install/: each installs by itself. TRIANGLE removes them all.",
          "Opcional: as DLCs (Jetstream, Blade Wolf, as missões VR, as roupas). Coloque os pacotes (qualquer nome) "
          "em PPSA48080/install/: cada um se instala sozinho. TRIÂNGULO remove todos.")};
    for (int r = 0; r < kContentRows; ++r) {
      const bool sel = r == content_row_, in = RowInstalled(r);
      const install::Source* src = SourceFor(r);
      const float fs = 40 * u;
      if (sel) dl->AddRectFilled(ImVec2(left - 30 * u, y + 8 * u), ImVec2(left - 20 * u, y + fs), P(kRed));
      dl->AddText(g_item, fs, ImVec2(left, y), P(sel ? kWhite : kGrey), names[r].c_str());
      std::string status = in && !(r == kRowDlc && src) ? T("INSTALLED", "INSTALADO")
                           : src                        ? T("READY TO INSTALL", "PRONTO PARA INSTALAR")
                                                        : T("NOT INSTALLED", "NÃO INSTALADO");
      if (r == kRowDlc && src) status = std::to_string(DlcWaiting()) + T(" READY TO INSTALL", " PRONTOS PARA INSTALAR");
      if (sel && Confirming(100 + r))
        status = T("PRESS TRIANGLE AGAIN TO UNINSTALL", "TRIÂNGULO DE NOVO: DESINSTALAR");
      dl->AddText(g_body, 28 * u, ImVec2(left + 430 * u, y + 8 * u),
                  P(in ? kWhite : src ? kWhite : (r != kRowDlc ? IM_COL32(230, 90, 70, 255) : kGrey)),
                  status.c_str());
      y += fs + 6 * u;
      if (src && !in) {
        dl->AddText(g_body, 22 * u, ImVec2(left + 430 * u, y), P(kGrey), Short(src->label, 44).c_str());
        y += 30 * u;
      }
      y += 18 * u;
    }
    y += 10 * u;
    y = DrawJob(dl, left, y, 820 * u) + 10 * u;
    // the rest of install/: what can't be installed, and why
    std::vector<std::string> notes;
    int avatar_items = 0;
    for (const auto& s : sources_) {
      if (s.kind == install::Kind::kArchive)
        notes.push_back(Short(s.label, 40) + T("  -  extract it on a PC first (7-Zip)", "  -  extraia num PC antes (7-Zip)"));
      else if (s.kind == install::Kind::kOther && s.label == install::kAvatarItemLabel)
        ++avatar_items;
      else if (s.kind == install::Kind::kOther)
        notes.push_back(Short(s.label, 60));
    }
    if (avatar_items)
      notes.push_back(std::to_string(avatar_items) +
                      (avatar_items == 1 ? T(" Xbox 360 avatar item", " item de avatar do Xbox 360")
                                         : T(" Xbox 360 avatar items", " itens de avatar do Xbox 360")) +
                      T("  -  not game DLC, not used here", "  -  não são DLC do jogo, não usados aqui"));
    if (!notes.empty()) {
      dl->AddText(g_body, 20 * u, ImVec2(left, y), P(kRed), T("ALSO IN PPSA48080/INSTALL", "TAMBÉM EM PPSA48080/INSTALL"));
      y += 34 * u;
      for (size_t i = 0; i < notes.size() && i < 5; ++i, y += 32 * u)
        dl->AddText(g_body, 24 * u, ImVec2(left, y), P(kGrey), notes[i].c_str());
    }
    // the focused row's help, at the right
    const float px = 1180 * u + page_dx_, pw = size.x - 140 * u - px;
    dl->AddRectFilled(ImVec2(px - 40 * u, 200 * u), ImVec2(px - 39 * u, 760 * u), P(IM_COL32(255, 255, 255, 40)));
    dl->AddText(g_body, 26 * u, ImVec2(px, 204 * u), P(kText), help[content_row_], nullptr, pw);
  }

  void DrawSaves(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, left = 140 * u + page_dx_;
    float y = 200 * u;
    char count[64];
    std::snprintf(count, sizeof(count), T("%d %s INSTALLED", "%d %s INSTALADOS"), installed_.saves,
                  installed_.saves == 1 ? "SAVE" : "SAVES");
    dl->AddText(g_body, 22 * u, ImVec2(left, y), P(kRed), count);
    y += 48 * u;
    const auto saves = SaveSources();
    const int rows = 1 + int(saves.size());
    // (an imported save's file deleted after the install: the list shorter under the selected row)
    saves_row_ = std::min(saves_row_, rows - 1);
    for (int r = 0; r < rows; ++r) {
      const bool sel = r == saves_row_;
      const float fs = 36 * u;
      if (sel) dl->AddRectFilled(ImVec2(left - 30 * u, y + 6 * u), ImVec2(left - 20 * u, y + fs), P(kRed));
      std::string label;
      if (r == 0) {
        label = T("BACK UP SAVES", "FAZER BACKUP DOS SAVES");
      } else {
        const install::Source* s = saves[size_t(r - 1)];
        label = (s->kind == install::Kind::kBackup ? T("RESTORE  ", "RESTAURAR  ") : T("IMPORT  ", "IMPORTAR  ")) +
                Short(s->label, 40);
        if (sel && Confirming(200 + r)) label = T("PRESS X AGAIN TO CONFIRM", "APERTE X DE NOVO PARA CONFIRMAR");
      }
      dl->AddText(g_item, fs, ImVec2(left, y), P(sel ? kWhite : kGrey), label.c_str());
      y += fs + 22 * u;
    }
    y += 10 * u;
    y = DrawJob(dl, left, y, 820 * u) + 10 * u;
    // the saves the app has, newest first
    if (!installed_.save_list.empty()) {
      Spaced(dl, g_body, 19 * u, ImVec2(left, y), P(kRed), T("YOUR SAVES", "SEUS SAVES"), 3 * u);
      y += 36 * u;
      for (size_t i = 0; i < installed_.save_list.size() && i < 6; ++i, y += 34 * u) {
        const auto& sv = installed_.save_list[i];
        std::string name = sv.name;
        std::replace(name.begin(), name.end(), '_', ' ');
        dl->AddText(g_body, 26 * u, ImVec2(left, y), P(kWhite), Short(name, 34).c_str());
        if (sv.modified)
          dl->AddText(g_body, 26 * u, ImVec2(left + 520 * u, y), P(kGrey),
                      Upper(Date(sv.modified, T("%b %d %Y  %I:%M %p", "%d %b %Y  %H:%M"))).c_str());
      }
    }
    const char* help =
        saves_row_ == 0
            ? T("Copies your saves, your trophies and your settings to PPSA48080/install/backups/. Copy that folder "
                "to a PC or a USB drive before deleting or reinstalling the app.",
                "Copia seus saves, seus troféus e seus ajustes para PPSA48080/install/backups/. Copie essa pasta "
                "para um PC ou um pendrive antes de apagar ou reinstalar o app.")
        : saves[size_t(saves_row_ - 1)]->kind == install::Kind::kBackup
            ? T("Puts this backup's saves, trophies and settings back, over the ones here.",
                "Devolve os saves, troféus e ajustes deste backup, por cima dos que estão aqui.")
            : T("Imports this Xbox 360 save (a package copied off a 360, with a USB drive or Horizon) into the app. "
                "A save of the same name here is replaced.",
                "Importa este save do Xbox 360 (um pacote copiado de um 360, com um pendrive ou o Horizon) para o "
                "app. Um save com o mesmo nome aqui é substituído.");
    const char* where =
        T("\n\nTo import a save, put the Xbox 360 save package (the file copied off the 360's drive: "
          "Content/<profile>/4B4E080A/00000001/...) in PPSA48080/install/. A backup made here, copied back into "
          "PPSA48080/install/ (or install/backups/), is listed to restore.",
          "\n\nPara importar um save, coloque o pacote de save do Xbox 360 (o arquivo copiado do disco do 360: "
          "Content/<perfil>/4B4E080A/00000001/...) em PPSA48080/install/. Um backup feito aqui, copiado de volta "
          "para PPSA48080/install/ (ou install/backups/), aparece para restaurar.");
    const std::string text = std::string(help) + (saves.empty() ? where : "");
    const float px = 1180 * u + page_dx_, pw = size.x - 140 * u - px;
    dl->AddRectFilled(ImVec2(px - 40 * u, 200 * u), ImVec2(px - 39 * u, 760 * u), P(IM_COL32(255, 255, 255, 40)));
    dl->AddText(g_body, 26 * u, ImVec2(px, 204 * u), P(kText), text.c_str(), nullptr, pw);
  }

  // SETTINGS' left side: the game, as on HOME (its logo with the accent's bar, pulsing while the
  // pad is on it), its settings at the right.
  void DrawSettingsGame(ImDrawList* dl, float left, float top) {
    const float u = u_;
    Spaced(dl, g_body, 19 * u, ImVec2(left, top), P(kRed), T("GAME", "JOGO"), 3 * u);
    const float y = top + 46 * u;
    float h = 53 * u;
    if (logo_) h = std::min(h, 330 * u * logo_.h / logo_.w);  // (a wide logo kept to the column)
    const float pulse = in_list_ ? 1.0f : 0.7f + 0.3f * std::sin(time_ * 5.0f);
    dl->AddRectFilled(ImVec2(left - 38 * u, y + h * 0.12f), ImVec2(left - 24 * u, y + h * 0.88f),
                      P((kRed & 0x00FFFFFFu) | (ImU32(255 * pulse) << 24)));
    if (logo_)
      dl->AddImage(logo_.id, ImVec2(left, y), ImVec2(left + logo_.w * h / logo_.h, y + h), ImVec2(0, 0), ImVec2(1, 1),
                   P(kWhite));
    else
      dl->AddText(g_item, h * 0.7f, ImVec2(left, y), P(kWhite), "METAL GEAR RISING: REVENGEANCE");
  }

  void DrawSettings(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, left = 580 * u + page_dx_;
    const auto lines = SettingsLines();
    const float fs = 36 * u, top = 190 * u, bottom = size.y - 120 * u;
    const float px = 1360 * u + page_dx_, pw = size.x - 140 * u - px;  // (the help, at the right)
    DrawSettingsGame(dl, 140 * u + page_dx_, top);
    dl->AddRectFilled(ImVec2(left - 60 * u, 190 * u), ImVec2(left - 59 * u, 760 * u), P(IM_COL32(255, 255, 255, 40)));
    // where each row and section heading goes (scrolled so the focused row stays in view)
    std::vector<float> row_y(kSettingsRows, 0.0f), head_y(kSettingsRows, -1.0f);
    float y = 0;
    for (int r = 0; r < kSettingsRows; ++r) {
      if (!r || std::strcmp(lines[size_t(r - 1)].section, lines[size_t(r)].section) != 0) {
        if (r) y += 14 * u;
        head_y[size_t(r)] = y;
        y += 36 * u;
      }
      row_y[size_t(r)] = y;
      y += fs + 16 * u;
    }
    const float view = bottom - top;
    const float want = std::clamp(row_y[size_t(row_)] - view * 0.45f, 0.0f, std::max(0.0f, y - view));
    settings_scroll_ += (want - settings_scroll_) * 0.25f;
    dl->PushClipRect(ImVec2(0, top - 4 * u), ImVec2(px - 40 * u, bottom), true);
    for (int r = 0; r < kSettingsRows; ++r) {
      const SettingLine& l = lines[size_t(r)];
      if (head_y[size_t(r)] >= 0)
        Spaced(dl, g_body, 19 * u, ImVec2(left, top + head_y[size_t(r)] - settings_scroll_), P(kRed), l.section,
               3 * u);
      y = top + row_y[size_t(r)] - settings_scroll_;
      const bool sel = in_list_ && r == row_;
      const ImU32 col = !l.enabled ? kDim : sel ? kWhite : kGrey;
      if (sel) dl->AddRectFilled(ImVec2(left - 30 * u, y + 8 * u), ImVec2(left - 20 * u, y + fs), P(kRed));
      dl->AddText(g_item, fs, ImVec2(left, y), P(col), l.label);
      const std::string v = l.slider || !l.enabled ? l.value : "<  " + l.value + "  >";
      // (a value too wide for its column, e.g. AUTO (PORTUGUÊS (BR)), drawn smaller instead of cut off)
      const float room = px - 48 * u - (left + 380 * u), vw = g_item->CalcTextSizeA(fs, FLT_MAX, 0, v.c_str()).x;
      const float vs = vw > room ? fs * room / vw : fs;
      dl->AddText(g_item, vs, ImVec2(left + 380 * u, y + (fs - vs) * 0.6f), P(sel ? (l.enabled ? kRed : kDim) : col),
                  v.c_str());
      if (l.slider) {
        const float x0 = left + 480 * u, w = 220 * u, yy = y + fs * 0.6f;
        dl->AddRectFilled(ImVec2(x0, yy - 3 * u), ImVec2(x0 + w, yy + 3 * u), P(kDim));
        dl->AddRectFilled(ImVec2(x0, yy - 3 * u), ImVec2(x0 + w * settings_.music / 100.0f, yy + 3 * u),
                          P(sel ? kRed : kGrey));
      }
    }
    dl->PopClipRect();
    // the focused row's help, at the right (on the game: what it's for)
    dl->AddRectFilled(ImVec2(px - 40 * u, 190 * u), ImVec2(px - 39 * u, 760 * u), P(IM_COL32(255, 255, 255, 40)));
    dl->AddText(g_item, 34 * u, ImVec2(px, 190 * u), P(kWhite), in_list_ ? lines[size_t(row_)].label : "METAL GEAR RISING: REVENGEANCE");
    const char* about = T("Metal Gear Rising: Revengeance's settings. X or RIGHT to change them. SQUARE puts back the recommended settings, the ones it was tested with.",
                  "Configurações de Metal Gear Rising: Revengeance. X ou DIREITA para mudá-las. QUADRADO volta às configurações recomendadas, as que foram testadas.");
    dl->AddText(g_body, 26 * u, ImVec2(px, 244 * u), P(kText), in_list_ ? lines[size_t(row_)].help : about, nullptr, pw);
    if (Confirming(300))
      dl->AddText(g_body, 22 * u, ImVec2(px, 676 * u), P(kRed),
                  T("PRESS SQUARE AGAIN TO PUT BACK THE RECOMMENDED SETTINGS", "APERTE QUADRADO DE NOVO PARA VOLTAR ÀS CONFIGURAÇÕES RECOMENDADAS"), nullptr, pw);
    else if (time_ - reset_t_ < 3.0f)
      dl->AddText(g_body, 22 * u, ImVec2(px, 700 * u), P(kRed),
                  T("RECOMMENDED SETTINGS PUT BACK", "CONFIGURAÇÕES RECOMENDADAS RESTAURADAS"));
    else
      dl->AddText(g_body, 22 * u, ImVec2(px, 700 * u), P(kDim), T("Saved when you press PLAY.", "Salvo quando você aperta JOGAR."));
  }

  void DrawTrophies(ImDrawList* dl, const ImVec2& size, float dt) {
    const float u = u_;
    if (!trophies_.loaded) {
      dl->AddText(g_item, 44 * u, ImVec2(140 * u + page_dx_, 220 * u), P(kWhite),
                  T("START THE GAME ONCE", "INICIE O JOGO UMA VEZ"));
      dl->AddText(g_body, 28 * u, ImVec2(140 * u + page_dx_, 290 * u), P(kGrey),
                  T("The trophy list comes from the game itself: start it once, and the next time the menu opens "
                    "your trophies are here, with the ones you've earned.",
                    "A lista de troféus vem do próprio jogo: inicie-o uma vez, e da próxima vez que o menu abrir "
                    "seus troféus estarão aqui, com os que você já conquistou."),
                  nullptr, 1000 * u);
      return;
    }
    const int n = int(items_.size());
    if (!n) return;
    trophy_ = std::clamp(trophy_, 0, n - 1);
    detail_in_ = std::min(1.0f, detail_in_ + dt * 6.0f);

    // the list at the left: group headings, then each trophy
    struct Row {
      int item;  // -1: a heading
      int group;
    };
    std::vector<Row> rows;
    int counts[3] = {};
    for (const Item& it : items_) ++counts[it.group];
    int sel_row = 0;
    for (int i = 0; i < n; ++i) {
      if (i == 0 || items_[size_t(i) - 1].group != items_[size_t(i)].group) rows.push_back({-1, items_[size_t(i)].group});
      if (i == trophy_) sel_row = int(rows.size());
      rows.push_back({i, items_[size_t(i)].group});
    }
    const float row_h = 64 * u, top = 172 * u, bottom = size.y - 130 * u;
    const float view = bottom - top;
    const float want = std::clamp(sel_row * row_h - view * 0.4f, 0.0f, std::max(0.0f, rows.size() * row_h - view));
    scroll_ += (want - scroll_) * std::min(1.0f, dt * 12.0f);
    const float x = 140 * u + page_dx_, right = 940 * u + page_dx_;
    const char* const kGroupNames[] = {T("EARNED", "CONQUISTADOS"), T("NOT EARNED YET", "AINDA NÃO CONQUISTADOS"),
                                       T("ONLINE ONLY", "SÓ ONLINE")};
    dl->PushClipRect(ImVec2(0, top), ImVec2(size.x, bottom), true);
    for (size_t r = 0; r < rows.size(); ++r) {
      const float ry = top + r * row_h - scroll_;
      if (ry + row_h < top || ry > bottom) continue;
      if (rows[r].item < 0) {
        const std::string head = std::string(kGroupNames[rows[r].group]) + "   " + std::to_string(counts[rows[r].group]);
        dl->AddText(g_body, 21 * u, ImVec2(x, ry + 30 * u), P(kRed), head.c_str());
        continue;
      }
      const Item& it = items_[size_t(rows[r].item)];
      const bool sel = rows[r].item == trophy_, earned = Earned(it);
      if (sel) dl->AddRectFilled(ImVec2(x - 16 * u, ry + 4 * u), ImVec2(right + 10 * u, ry + row_h - 4 * u),
                                 P(IM_COL32(196, 22, 28, 52)), 6 * u);
      Icon(dl, it, x, ry + 8 * u, 48 * u, page_alpha_);
      const ImU32 col = sel ? kWhite : earned ? IM_COL32(210, 206, 200, 255) : kGrey;
      dl->AddText(g_item, 28 * u, ImVec2(x + 70 * u, ry + 13 * u), P(col),
                  Fit(g_item, 28 * u, NameOf(it), right - x - 130 * u).c_str());
      trophies::DrawCup(dl, ImVec2(right - 18 * u, ry + row_h * 0.5f), 30 * u, GradeOf(it), page_alpha_, earned);
    }
    dl->PopClipRect();

    // how far along, then the focused trophy
    const float px = 1040 * u + page_dx_, pw = size.x - 140 * u - px;
    float py = 180 * u;
    dl->AddRectFilled(ImVec2(px - 50 * u, top), ImVec2(px - 49 * u, bottom), P(IM_COL32(255, 255, 255, 40)));
    const std::string pct = std::to_string(trophies_.Percent()) + "%";
    dl->AddText(g_title, 72 * u, ImVec2(px, py - 10 * u), P(kWhite), pct.c_str());
    const float pctw = Width(g_title, 72 * u, pct);
    const std::string of = std::to_string(trophies_.earned) + T(" of ", " de ") + std::to_string(trophies_.earnable) +
                           T(" earned", " conquistados");
    dl->AddText(g_body, 26 * u, ImVec2(px + pctw + 24 * u, py + 34 * u), P(kGrey), of.c_str());
    float rx = px + pw;
    for (int g = 0; g < 3; ++g) {  // (bronze at the right, gold at the left)
      const std::string c = std::to_string(trophies_.grade_earned[g]) + "/" + std::to_string(trophies_.grade_total[g]);
      const float cw = Width(g_body, 24 * u, c);
      dl->AddText(g_body, 24 * u, ImVec2(rx - cw, py + 34 * u), P(trophies_.grade_earned[g] ? kWhite : kDim), c.c_str());
      trophies::DrawCup(dl, ImVec2(rx - cw - 20 * u, py + 48 * u), 26 * u, trophies::Grade(g), page_alpha_,
                        trophies_.grade_earned[g] > 0);
      rx -= cw + 60 * u;
    }
    py += 92 * u;
    dl->AddRectFilled(ImVec2(px, py), ImVec2(px + pw, py + 8 * u), P(IM_COL32(255, 255, 255, 30)));
    const float f = trophies_.points ? float(trophies_.points_earned) / float(trophies_.points) : 0.0f;
    if (f > 0) dl->AddRectFilled(ImVec2(px, py), ImVec2(px + std::max(4 * u, pw * f), py + 8 * u),
                                 P(trophies_.Platinum() ? trophies::GradeColor(trophies::Grade::kPlatinum) : kRed));
    py += 54 * u;

    const Item& it = items_[size_t(trophy_)];
    const float da = page_alpha_ * detail_in_;
    const float dx = px + (1 - detail_in_) * 14 * u;
    Icon(dl, it, dx, py, 112 * u, da);
    const trophies::Grade g = GradeOf(it);
    // (trophies::Grade's order)
    static constexpr const char* kGrades[] = {"BRONZE TROPHY", "SILVER TROPHY", "GOLD TROPHY", "PLATINUM TROPHY"};
    static constexpr const char* kGradesPt[] = {"TROFÉU DE BRONZE", "TROFÉU DE PRATA", "TROFÉU DE OURO",
                                                "TROFÉU DE PLATINA"};
    const std::string grade = T(kGrades[int(g) & 3], kGradesPt[int(g) & 3]);
    dl->AddText(g_body, 20 * u, ImVec2(dx + 136 * u, py + 8 * u), trophies::GradeColor(g, da), grade.c_str());
    dl->AddText(g_item, 36 * u, ImVec2(dx + 136 * u, py + 34 * u), A(kWhite, da), NameOf(it).c_str(), nullptr,
                pw - 136 * u);
    py += 138 * u;
    const std::string text = TextOf(it);
    dl->AddText(g_body, 27 * u, ImVec2(dx, py), A(kText, da), text.c_str(), nullptr, pw);
    py += g_body->CalcTextSizeA(27 * u, FLT_MAX, pw, text.c_str()).y + 34 * u;
    const trophies::Trophy* t = it.index < 0 ? nullptr : &trophies_.trophies[size_t(it.index)];
    std::string status;
    if (Earned(it))
      status = T("Earned ", "Conquistado em ") +
               Date(t ? t->earned : trophies_.last_earned, T("%b %d, %Y", "%d de %b de %Y"));
    else if (!t) status = std::to_string(trophies_.earnable - trophies_.earned) + T(" to go", " restantes");
    else if (t->online()) status = T("Not available offline", "Indisponível offline");
    else status = T("Not earned yet", "Ainda não conquistado");
    dl->AddText(g_body, 20 * u, ImVec2(dx, py), A(kDim, da), "STATUS");
    dl->AddText(g_body, 24 * u, ImVec2(dx + 170 * u, py - 2 * u), A(kWhite, da), status.c_str());
    if (t) {
      py += 40 * u;
      dl->AddText(g_body, 20 * u, ImVec2(dx, py), A(kDim, da), "GAMERSCORE");
      dl->AddText(g_body, 24 * u, ImVec2(dx + 170 * u, py - 2 * u), A(kWhite, da),
                  (std::to_string(t->gamerscore) + "G").c_str());
    }
  }

  void DrawCredits(ImDrawList* dl, const ImVec2& size) {
    const float u = u_, x = 140 * u + page_dx_, w = 860 * u;
    float y = 180 * u;
    dl->PushClipRect(ImVec2(0, 0), ImVec2(size.x, size.y - 120 * u), true);  // (not into the clock)
    auto entry = [&](const char* name, const char* text) {
      dl->AddText(g_item, 26 * u, ImVec2(x, y), P(kWhite), name);
      y += 34 * u;
      dl->AddText(g_body, 20 * u, ImVec2(x, y), P(kGrey), text, nullptr, w);
      y += g_body->CalcTextSizeA(20 * u, FLT_MAX, w, text).y + 20 * u;
    };
    // the project
    dl->AddText(g_title, 60 * u, ImVec2(x, y - 6 * u), P(kWhite), "METAL GEAR RISING");
    const float tw = Width(g_title, 60 * u, "METAL GEAR RISING");
    Spaced(dl, g_item, 30 * u, ImVec2(x + tw + 22 * u, y + 24 * u), P(kRed), "REPLATINUM", 6 * u);
    y += 84 * u;
    entry(T("BY CHAOSTHEORY1075", "POR CHAOSTHEORY1075"), "github.com/ChaosTheory1075/mgr-ps5");
    dl->AddText(g_body, 20 * u, ImVec2(x, y), P(kRed), T("ALL THE CREDIT GOES TO", "TODO O CRÉDITO VAI PARA"));
    y += 40 * u;
    entry("GTA IV FOR PS5  -  ELRIPALDA",
          T("The PS5 port this one is built on, top to bottom: the PS5 runtime, graphics and sound, the hub this menu "
            "copies, the trophies and their pop-up, and the installer payload. github.com/elripalda/gta4-ps5",
            "O port de PS5 em que este se baseia, de cima a baixo: o runtime do PS5, gráficos e som, o hub que este "
            "menu copia, os troféus e o aviso deles, e o payload do instalador. github.com/elripalda/gta4-ps5"));
    entry("LIBERTY RECOMPILED  -  OZORDI  /  VADUUR",
          T("OZORDI's recompilation of GTA IV and vaduur's LibertyRecompAndroid, which GTA IV for PS5 starts from.",
            "A recompilação de GTA IV do OZORDI e o LibertyRecompAndroid do vaduur, de onde GTA IV for PS5 parte."));
    entry(T("REXGLUE AND XENIA", "REXGLUE E XENIA"),
          T("The static recompiler and runtime under all of it, and the Xenia team's Xbox 360 emulator it grew from "
            "(Xenia Canary's XMA decoding is what plays the game's sound here).",
            "O recompilador estático e o runtime por baixo de tudo, e o emulador de Xbox 360 da equipe do Xenia de "
            "onde ele nasceu (a decodificação XMA do Xenia Canary é o que toca o som do jogo aqui)."));
    entry("CRACKDOWN RECOMPILED  -  SAULOB",
          T("Whose ReXGlue patches and frame rate work this port's GPU and timing fixes come from. "
            "github.com/saulob/crackdown-xbox360-recompiled",
            "Dos patches de ReXGlue e do trabalho de taxa de quadros dele vêm as correções de GPU e de tempo deste "
            "port. github.com/saulob/crackdown-xbox360-recompiled"));
    entry("CRACKDOWN: REACTIVATED  /  MAX PAYNE 3 REPRESCRIBED",
          T("The sister ports this one grew out of: the same menu, installer, saves and trophies.",
            "Os ports irmãos de onde este nasceu: o mesmo menu, instalador, saves e troféus."));

    const float px = 1060 * u + page_dx_, pw = size.x - 140 * u - px;
    float py = 180 * u;
    // the shout-out, on a panel of its own
    {
      const char* thanks =
          T("For Raiden's best day: Blade Mode, the parries, Jetstream Sam, and a soundtrack that sings along to "
            "every boss. Rules of nature.",
            "Pelo melhor dia do Raiden: o Blade Mode, os contra-ataques, Jetstream Sam e uma trilha sonora que canta "
            "junto em cada chefe. Rules of nature.");
      const float th = g_body->CalcTextSizeA(22 * u, FLT_MAX, pw - 48 * u, thanks).y;
      dl->AddRectFilled(ImVec2(px - 24 * u, py - 16 * u), ImVec2(px + pw, py + 96 * u + th),
                        P(IM_COL32(8, 8, 8, 170)), 6 * u);
      dl->AddRectFilled(ImVec2(px - 24 * u, py - 16 * u), ImVec2(px - 18 * u, py + 96 * u + th), P(kRed));
      dl->AddText(g_body, 20 * u, ImVec2(px, py), P(kRed), T("SPECIAL THANKS", "AGRADECIMENTOS ESPECIAIS"));
      dl->AddText(g_item, 40 * u, ImVec2(px, py + 30 * u), P(kWhite), "PLATINUMGAMES  &  KOJIMA PRODUCTIONS");
      dl->AddText(g_body, 22 * u, ImVec2(px, py + 84 * u), P(kGrey), thanks, nullptr, pw - 48 * u);
      py += 96 * u + th + 46 * u;
    }
    if (!song_.empty()) {
      dl->AddText(g_body, 20 * u, ImVec2(px, py), P(kRed), T("MENU SONG", "MÚSICA DO MENU"));
      dl->AddText(g_body, 24 * u, ImVec2(px, py + 32 * u), P(kGrey), Fit(g_body, 24 * u, song_, pw).c_str());
      py += 90 * u;
    }
    dl->AddText(g_body, 20 * u, ImVec2(px, py), P(kRed), T("PLEASE NOTE", "OBSERVAÇÃO"));
    py += 36 * u;
    const char* note =
        T("An unofficial fan project, not affiliated with or endorsed by Konami, PlatinumGames, Microsoft or Sony. "
          "Metal Gear and all related names belong to their owners. No game files are included: you need your own "
          "copy of Metal Gear Rising: Revengeance for the Xbox 360.",
          "Um projeto de fã não oficial, sem vínculo ou aprovação da Konami, PlatinumGames, Microsoft ou Sony. "
          "Metal Gear e todos os nomes relacionados pertencem aos seus donos. Nenhum arquivo do jogo está incluído: "
          "você precisa da sua própria cópia de Metal Gear Rising: Revengeance para Xbox 360.");
    dl->AddText(g_body, 20 * u, ImVec2(px, py), P(kGrey), note, nullptr, pw);
    py += g_body->CalcTextSizeA(20 * u, FLT_MAX, pw, note).y + 28 * u;
    dl->AddText(g_body, 20 * u, ImVec2(px, py), P(kRed), T("BUILT WITH", "FEITO COM"));
    py += 36 * u;
    dl->AddText(g_body, 19 * u, ImVec2(px, py), P(kGrey),
                T("PS5 Payload SDK  /  Mesa RADV (Vulkan)  /  Dear ImGui\nstb_image, dr_mp3, zlib, xxHash  /  Oswald "
                  "and Inter (SIL Open Font License)\nBlackBearReloaded's PS5 AT9 Converter (the home screen music)",
                  "PS5 Payload SDK  /  Mesa RADV (Vulkan)  /  Dear ImGui\nstb_image, dr_mp3, zlib, xxHash  /  Oswald "
                  "e Inter (SIL Open Font License)\nPS5 AT9 Converter do BlackBearReloaded (a música da tela inicial)"),
                nullptr, pw);
    dl->PopClipRect();
  }

  // ---- files ----

  void StartMusic(const fs::path& dir) {
    std::error_code ec;
    if (!fs::is_directory(dir, ec)) return;
    for (const auto& e : fs::directory_iterator(dir, ec)) {
      if (!e.is_regular_file() || !gta4ps5::sound::CanOpen(e.path())) continue;
      if (!gta4ps5::sound::StartOutput()) {
        REXLOG_WARN("Metal Gear Rising: Revengeance menu: no audio port for the menu's song");
        return;
      }
      if (auto src = gta4ps5::sound::Open(e.path())) {
        music_ = gta4ps5::sound::NewVoice();
        music_->SetVolume(settings_.music / 100.0f);
        music_->Play(std::move(src), true);
        song_ = e.path().stem().string();
        REXLOG_INFO("Metal Gear Rising: Revengeance menu: playing {}", e.path().filename().string());
        return;
      }
    }
  }

  Image Load(const fs::path& file) {
    if (!immediate_) return {};
    int w = 0, h = 0, n = 0;
    unsigned char* px = stbi_load(file.string().c_str(), &w, &h, &n, 4);
    if (!px) return {};
    auto tex = immediate_->CreateTexture(uint32_t(w), uint32_t(h), rex::ui::ImmediateTextureFilter::kLinear, false, px);
    stbi_image_free(px);
    if (!tex) return {};
    Image img{reinterpret_cast<ImTextureID>(tex.get()), float(w), float(h)};
    g_textures->push_back(std::move(tex));
    return img;
  }

  rex::ui::ImmediateDrawer* immediate_ = nullptr;
  fs::path app_, user_data_;
  std::function<void(MenuChoice)> play_;
  Settings settings_;
  bool in_list_ = false;  // SETTINGS: in the game's settings (false: on the game, at the left)
  float reset_t_ = -100;  // (when SQUARE last put the recommended settings back)
  int hd_movies_ = 0;  // (the HD cutscenes in movie_hd/)
  Pad pad_;
  Image background_, logo_, title_;  // (title_: hub/title.png, the header's logo)
  gta4ps5::sound::Voice* music_ = nullptr;
  std::string song_;
  install::Installed installed_;
  std::vector<install::Source> sources_;
  std::set<std::string> tried_;  // (installed by themselves once a session)
  uint32_t job_generation_ = 0;
  int content_row_ = 0, saves_row_ = 0, confirm_key_ = -1;
  float result_t_ = -100, confirm_t_ = -100, missing_flash_ = 0;
  bool ask_leftovers_ = false;
  uint64_t leftover_bytes_ = 0;
  Page page_ = kHome;
  int row_ = kAntiAliasing, trophy_ = 0;
  float settings_scroll_ = 0;  // (the settings list's scroll, eased)
  trophies::List trophies_;
  std::vector<Item> items_;
  std::map<uint32_t, Image> pictures_;
  int pictures_this_frame_ = 0;
  float time_ = 0, leave_t_ = 0, fade_ = 0, u_ = 1, page_in_ = 1, page_alpha_ = 1, page_dx_ = 0;
  float tab_x_ = 0, tab_w_ = 0, tab_target_x_ = 0, tab_target_w_ = 0, page_dark_ = 0, scroll_ = 0, detail_in_ = 1;
  bool leaving_ = false, done_ = false;
};

ImFont* AddFont(ImFontAtlas* atlas, const unsigned char* begin, const unsigned char* end, float size) {
  ImFontConfig cfg;
  cfg.FontDataOwnedByAtlas = false;  // (built into the app)
  cfg.OversampleH = 2;
  return atlas->AddFontFromMemoryTTF(const_cast<unsigned char*>(begin), int(end - begin), size, &cfg);
}

}  // namespace

void ConfigureMenuFonts(ImFontAtlas* atlas) {
  // (at the 4K screen's sizes: drawn smaller on a 1080p one)
  g_title = AddFont(atlas, mgrps5_font_title, mgrps5_font_title_end, 240.0f);
  g_item = AddFont(atlas, mgrps5_font_item, mgrps5_font_item_end, 128.0f);
  g_body = AddFont(atlas, mgrps5_font_body, mgrps5_font_body_end, 56.0f);
}

ImFont* MenuBodyFont() { return g_body; }
ImFont* MenuItemFont() { return g_item; }

void ShowMenu(rex::ui::ImGuiDrawer* drawer, rex::ui::ImmediateDrawer* immediate, const fs::path& app,
              std::function<void(MenuChoice)> play) {
  REXLOG_INFO("Metal Gear Rising: Revengeance menu: shown");
  new MenuDialog(drawer, immediate, app, std::move(play));  // (the dialog owns itself)
}

}  // namespace mgrps5

#endif  // REX_PLATFORM_PS5
