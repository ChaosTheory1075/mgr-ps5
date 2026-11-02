// Metal Gear Rising: Revengeance RePlatinum (PS5) - the in-game quick menu (see mgr_quick_menu.h).
//
// The controller is read where the game reads it: sub_823236C0, the title's XInputGetState (r3 the user,
// r4 the X_INPUT_STATE; XamInputGetState with flags 1). After it runs, the menu takes what was pressed and,
// while open, blanks the state the game gets. The cheats themselves act in mgr_game_overlay.cpp, once a
// frame, on the player character.
#include "mgr_quick_menu.h"
#if REX_PLATFORM_PS5

#include <algorithm>
#include <atomic>
#include <bit>
#include <cfloat>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <imgui.h>
#include <rex/cvar.h>
#include <rex/input/sony_feedback.h>
#include <rex/logging.h>

#include "mgr_menu.h"
#include "mgr_text.h"

REXCVAR_DEFINE_BOOL(mgr_cheat_menu, true, "Metal Gear Rising",
                    "L3 + R3 opens the quick menu over the game: the cheats, the FPS counter, the DualSense");
REXCVAR_DEFINE_BOOL(mgr_cheat_health, false, "Metal Gear Rising", "Cheat: Raiden's health kept full");
REXCVAR_DEFINE_BOOL(mgr_cheat_fuel, false, "Metal Gear Rising",
                    "Cheat: the fuel cells kept full (Blade Mode and Ripper Mode without end)");
REXCVAR_DECLARE(std::string, mgr_fps_counter);

namespace mgrps5 {
namespace {

constexpr const char* kMenuFile = "/app0/menu.ini";

// X_INPUT_GAMEPAD in the X_INPUT_STATE (big-endian): buttons, the triggers, the sticks.
constexpr uint32_t kGamepad = 4, kGamepadSize = 12, kThumbLY = 6;
constexpr uint16_t kUp = 0x0001, kDown = 0x0002, kLeft = 0x0004, kRight = 0x0008, kL3 = 0x0040, kR3 = 0x0080,
                   kCross = 0x1000, kCircle = 0x2000;
constexpr int kStickDeadzone = 16000;

enum Nav : uint8_t { kNavUp = 1, kNavDown, kNavLeft, kNavRight, kNavSelect, kNavClose };

std::unique_ptr<QuickMenu> g_menu;
std::atomic<bool> g_open{false};
std::mutex g_mutex;
std::deque<uint8_t> g_events;  // guarded by g_mutex
uint16_t g_previous = 0;       // the game thread's
bool g_swallow = false;        // blank the pad until everything is let go (after closing)

uint16_t LoadBe16(uint8_t* base, uint32_t address) {
  uint16_t v;
  std::memcpy(&v, base + address, 2);
  return std::byteswap(v);
}

void Push(uint8_t event) {
  std::lock_guard lock(g_mutex);
  if (g_events.size() < 16) g_events.push_back(event);
}

uint8_t Take() {
  std::lock_guard lock(g_mutex);
  if (g_events.empty()) return 0;
  const uint8_t e = g_events.front();
  g_events.pop_front();
  return e;
}

// menu.ini's `key` set to `value`, the other lines kept (the app's menu reads it at the next start).
void SetMenuValue(const char* key, int value) {
  std::vector<std::string> lines;
  if (std::FILE* f = std::fopen(kMenuFile, "rb")) {
    char line[256];
    while (std::fgets(line, sizeof(line), f)) lines.emplace_back(line);
    std::fclose(f);
  }
  const std::string prefix = std::string(key) + " =";
  const std::string entry = prefix + " " + std::to_string(value) + "\n";
  bool found = false;
  for (std::string& l : lines)
    if (l.rfind(prefix, 0) == 0) l = entry, found = true;
  if (!found) lines.push_back(entry);
  if (std::FILE* f = std::fopen(kMenuFile, "wb")) {
    for (const std::string& l : lines) std::fputs(l.c_str(), f);
    std::fclose(f);
  }
}

// ---- the rows ----

enum RowId { kHealth, kFuel, kCounter, kDualSense, kRows };

struct Row {
  const char* section;  // a heading over the row, or nullptr
  const char* label;
  const char* section_pt;  // (the two in Portuguese: mgr_text.h)
  const char* label_pt;
};
constexpr Row kRowInfo[kRows] = {
    {"CHEATS", "Infinite Health", "TRAPAÇAS", "Vida Infinita"},
    {nullptr, "Infinite Fuel Cells", nullptr, "Células de Energia Infinitas"},
    {"DISPLAY", "FPS Counter", "TELA", "Contador de FPS"},
    {"CONTROLLER", "DualSense Features", "CONTROLE", "Recursos do DualSense"},
};

int CounterMode() {
  const std::string m = REXCVAR_GET(mgr_fps_counter);
  return m == "detailed" ? 2 : m == "simple" ? 1 : 0;
}

std::string ValueOf(int row) {
  const char* on = T("ON", "LIGADO");
  const char* off = T("OFF", "DESLIGADO");
  switch (row) {
    case kHealth: return REXCVAR_GET(mgr_cheat_health) ? on : off;
    case kFuel: return REXCVAR_GET(mgr_cheat_fuel) ? on : off;
    case kCounter:
      return CounterMode() == 2 ? T("DETAILED", "DETALHADO") : CounterMode() == 1 ? T("SIMPLE", "SIMPLES") : off;
    default: return rex::input::sony::GetOptions().enabled ? on : off;
  }
}

// One step forward (or back) of the row's value.
void Change(int row, bool back) {
  switch (row) {
    case kHealth: {
      const bool on = !REXCVAR_GET(mgr_cheat_health);
      rex::cvar::SetFlagByName("mgr_cheat_health", on ? "true" : "false");
      SetMenuValue("cheat_health", on ? 1 : 0);
      REXLOG_INFO("Quick menu: infinite health {}", on ? "on" : "off");
      break;
    }
    case kFuel: {
      const bool on = !REXCVAR_GET(mgr_cheat_fuel);
      rex::cvar::SetFlagByName("mgr_cheat_fuel", on ? "true" : "false");
      SetMenuValue("cheat_fuel", on ? 1 : 0);
      REXLOG_INFO("Quick menu: infinite fuel cells {}", on ? "on" : "off");
      break;
    }
    case kCounter: {
      static constexpr const char* kModes[] = {"off", "simple", "detailed"};
      const int mode = (CounterMode() + (back ? 2 : 1)) % 3;
      rex::cvar::SetFlagByName("mgr_fps_counter", kModes[mode]);
      SetMenuValue("fps_counter", mode);
      break;
    }
    default: {
      const bool on = !rex::input::sony::GetOptions().enabled;
      rex::input::sony::SetFeaturesEnabled(on);
      SetMenuValue("dualsense", on ? 1 : 0);
      break;
    }
  }
}

constexpr ImU32 kWhite = IM_COL32(236, 232, 226, 255), kGrey = IM_COL32(150, 146, 140, 255),
                kRed = IM_COL32(196, 22, 28, 255);

ImU32 Fade(ImU32 c, float a) { return (c & 0x00FFFFFFu) | (ImU32(float(c >> 24) * a) << 24); }

}  // namespace

void FilterPad(uint8_t* base, uint32_t state) {
  if (!REXCVAR_GET(mgr_cheat_menu) && !g_open.load(std::memory_order_relaxed)) return;
  uint16_t buttons = LoadBe16(base, state + kGamepad);
  const int ly = int16_t(LoadBe16(base, state + kGamepad + kThumbLY));
  if (ly > kStickDeadzone) buttons |= kUp;  // (the left stick as the D-pad)
  if (ly < -kStickDeadzone) buttons |= kDown;
  const uint16_t pressed = buttons & ~g_previous;
  const bool combo = (buttons & (kL3 | kR3)) == (kL3 | kR3);
  const bool combo_pressed = combo && (pressed & (kL3 | kR3));
  g_previous = buttons;
  if (!g_open.load(std::memory_order_relaxed)) {
    if (combo_pressed) {
      { std::lock_guard lock(g_mutex); g_events.clear(); }
      g_open.store(true, std::memory_order_release);
      REXLOG_INFO("Quick menu: open");
    } else if (g_swallow && !buttons) {
      g_swallow = false;
    }
    if (!g_open.load(std::memory_order_relaxed) && !g_swallow) return;
  } else {
    if (combo_pressed || (pressed & kCircle)) {
      g_open.store(false, std::memory_order_release);
      g_swallow = true;
      Push(kNavClose);
    } else {
      if (pressed & kUp) Push(kNavUp);
      if (pressed & kDown) Push(kNavDown);
      if (pressed & kLeft) Push(kNavLeft);
      if (pressed & kRight) Push(kNavRight);
      if (pressed & kCross) Push(kNavSelect);
    }
  }
  std::memset(base + state + kGamepad, 0, kGamepadSize);
}

QuickMenu::QuickMenu(rex::ui::ImGuiDrawer* drawer) : ImGuiDialog(drawer) {}

bool QuickMenu::WantsContinuousRepaint() const { return g_open.load(std::memory_order_relaxed) || shown_ > 0; }

void QuickMenu::OnDraw(ImGuiIO& io) {
  const bool open = g_open.load(std::memory_order_acquire);
  shown_ = std::clamp(shown_ + (open ? 1.0f : -1.0f) * std::min(io.DeltaTime, 0.1f) * 8.0f, 0.0f, 1.0f);
  for (uint8_t e; (e = Take());) {
    if (e == kNavUp) row_ = (row_ + kRows - 1) % kRows;
    if (e == kNavDown) row_ = (row_ + 1) % kRows;
    if (e == kNavLeft) Change(row_, true);
    if (e == kNavRight || e == kNavSelect) Change(row_, false);
  }
  if (shown_ <= 0) return;

  const ImVec2 size = io.DisplaySize;
  const float u = std::min(size.x / 1920.0f, size.y / 1080.0f), a = shown_;
  ImDrawList* dl = ImGui::GetForegroundDrawList();
  ImFont* item = MenuItemFont() ? MenuItemFont() : ImGui::GetFont();
  ImFont* body = MenuBodyFont() ? MenuBodyFont() : ImGui::GetFont();
  int headings = 0;
  for (const Row& r : kRowInfo) headings += r.section ? 1 : 0;
  const float row_h = 40 * u, head_h = 44 * u, w = 760 * u;
  const float h = 110 * u + kRows * row_h + headings * head_h + 70 * u;
  const float x = (size.x - w) * 0.5f, y0 = (size.y - h) * 0.5f;
  dl->AddRectFilled(ImVec2(0, 0), size, Fade(IM_COL32(0, 0, 0, 110), a));
  dl->AddRectFilled(ImVec2(x, y0), ImVec2(x + w, y0 + h), Fade(IM_COL32(8, 8, 10, 235), a), 10 * u);
  dl->AddRectFilled(ImVec2(x, y0), ImVec2(x + 8 * u, y0 + h), Fade(kRed, a), 10 * u, ImDrawFlags_RoundCornersLeft);
  dl->AddText(item, 46 * u, ImVec2(x + 40 * u, y0 + 26 * u), Fade(kWhite, a), T("QUICK MENU", "MENU RÁPIDO"));
  float y = y0 + 100 * u;
  for (int i = 0; i < kRows; ++i) {
    const Row& r = kRowInfo[i];
    if (r.section) {
      y += 10 * u;
      dl->AddText(body, 20 * u, ImVec2(x + 40 * u, y), Fade(kRed, a), T(r.section, r.section_pt));
      dl->AddRectFilled(ImVec2(x + 40 * u, y + 28 * u), ImVec2(x + w - 40 * u, y + 29 * u),
                        Fade(IM_COL32(255, 255, 255, 40), a));
      y += head_h - 10 * u;
    }
    const bool sel = i == row_;
    if (sel)
      dl->AddRectFilled(ImVec2(x + 24 * u, y + 2 * u), ImVec2(x + w - 24 * u, y + row_h - 2 * u),
                        Fade(IM_COL32(196, 22, 28, 50), a), 4 * u);
    dl->AddText(item, 28 * u, ImVec2(x + 40 * u, y + 5 * u), Fade(sel ? kWhite : kGrey, a), T(r.label, r.label_pt));
    const std::string v = sel ? "<  " + ValueOf(i) + "  >" : ValueOf(i);
    const float vw = item->CalcTextSizeA(28 * u, FLT_MAX, 0, v.c_str()).x;
    dl->AddText(item, 28 * u, ImVec2(x + w - 40 * u - vw, y + 5 * u), Fade(sel ? kRed : kGrey, a), v.c_str());
    y += row_h;
  }
  dl->AddText(body, 20 * u, ImVec2(x + 40 * u, y0 + h - 46 * u), Fade(kGrey, a),
              T("UP DOWN  MOVE      LEFT RIGHT / X  CHANGE      O / L3+R3  CLOSE",
                "CIMA BAIXO  MOVER      ESQ. DIR. / X  MUDAR      O / L3+R3  FECHAR"));
}

void StartQuickMenu(rex::ui::ImGuiDrawer* drawer) {
  if (!g_menu && drawer) g_menu = std::make_unique<QuickMenu>(drawer);
}

}  // namespace mgrps5

#endif  // REX_PLATFORM_PS5
