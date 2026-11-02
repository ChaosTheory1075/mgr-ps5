// Metal Gear Rising: Revengeance RePlatinum (PS5) - the frame rate counter and the
// DualSense's features (see mgr_game_overlay.h).
#include "mgr_game_overlay.h"

#if REX_PLATFORM_PS5

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include <SDL3/SDL_timer.h>
#include <imgui.h>
#include <rex/cvar.h>
#include <rex/frame_stats.h>
#include <rex/input/sony_feedback.h>
#include <rex/logging.h>
#include <rex/memory.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xmemory.h>

#include "mgr_menu.h"

REXCVAR_DEFINE_STRING(mgr_fps_counter, "off", "Metal Gear Rising",
                      "The frame rate counter while playing: off, simple (frames a second and the frame time) or "
                      "detailed (also the slowest frames and a graph)");
REXCVAR_DEFINE_BOOL(mgr_lightbar_effects, true, "Metal Gear Rising",
                    "The light bar flashes for hits and repairs and pulses in Ripper Mode and at low health "
                    "(off: it shows only the health)");
REXCVAR_DECLARE(bool, mgr_cheat_health);
REXCVAR_DECLARE(bool, mgr_cheat_fuel);

namespace mgrps5 {

namespace {

std::unique_ptr<GameOverlay> g_overlay;

// The latest player character the game made, and the class (vtable) it had when
// first seen alive: a different one later means it was destroyed.
std::atomic<uint32_t> g_player{0};
uint32_t g_player_seen = 0, g_player_vtable = 0;

// green at 60 or better, white at 30, then yellow, then red
ImU32 RateColor(float ms) {
  return ms <= 17.5f ? IM_COL32(120, 230, 140, 255)
         : ms <= 34.5f ? IM_COL32(244, 245, 247, 255)
         : ms <= 50.5f ? IM_COL32(245, 200, 80, 255)
                       : IM_COL32(240, 90, 80, 255);
}

// ---- the game's state, read from its memory (Title Update 4's default.xex) ----
//
// The player character (Pl0000, the base of Raiden's and the DLC stories'
// classes; sub_822B4198 constructs it): as the PC version's Pl0000 (the MGR
// modding SDKs) where it was checked, except the health: an int at +0x860 and
// its most at +0x864 on the Xbox 360 (the PC's +0x870/+0x874; seen live in
// Title Update 4 as 610 of 800 with the HUD at 76%); Ripper Mode on at +0x3274 (EnableRipperMode,
// sub_82A83620, sets it, DisableRipperMode, sub_82A83720, clears it); the
// fuel cells, an array of 24-byte entries at *(+0x3970), their count at
// +0x3978: each one's fuel a float at +4, its most at +0xC, in use while
// +0x14 is 0 (DisableRipperMode adds them up so).
struct Guest {
  rex::memory::Memory* memory;

  // (a page that's there: a pointer read from the game may be stale)
  bool Readable(uint32_t address, uint32_t size = 4) const {
    if (address < 0x40000000u) return false;
    auto* heap = memory->LookupHeap(address);
    uint32_t protect = 0;
    return heap && heap->QueryProtect(address, &protect) && (protect & rex::memory::kMemoryProtectRead) &&
           heap->QueryProtect(address + size - 1, &protect) && (protect & rex::memory::kMemoryProtectRead);
  }
  uint32_t U32(uint32_t address) const {
    return rex::memory::load_and_swap<uint32_t>(memory->TranslateVirtual<uint8_t*>(address));
  }
  void Store32(uint32_t address, uint32_t value) const {
    rex::memory::store_and_swap<uint32_t>(memory->TranslateVirtual<uint8_t*>(address), value);
  }
  float F32(uint32_t address) const {
    const uint32_t bits = U32(address);
    float f;
    std::memcpy(&f, &bits, sizeof(f));
    return std::isfinite(f) ? f : 0.0f;
  }
};

struct Player {
  bool valid = false;
  uint32_t object = 0;
  int32_t health = 0, most = 0;
  float fuel = 0, fuel_most = 0;
  bool ripper = false;
};

Player ReadPlayer(const Guest& g) {
  Player p;
  const uint32_t object = g_player.load(std::memory_order_acquire);
  if (!object || !g.Readable(object, 0x3980)) return p;
  const uint32_t vtable = g.U32(object);
  if (object != g_player_seen) {
    g_player_seen = object;
    g_player_vtable = 0;
  }
  p.health = int32_t(g.U32(object + 0x860));
  p.most = int32_t(g.U32(object + 0x864));
  if (p.most <= 0 || p.most > 1000000 || p.health < 0 || p.health > p.most) return p;
  if (!g_player_vtable) {
    g_player_vtable = vtable;
    REXLOG_INFO("Metal Gear Rising: the player character at {:08X} (class {:08X}): health {} of {}", object, vtable,
                p.health, p.most);
  } else if (vtable != g_player_vtable) {
    return p;  // (destroyed)
  }
  p.valid = true;
  p.object = object;
  p.ripper = g.U32(object + 0x3274) != 0;
  const uint32_t cells = g.U32(object + 0x3970), count = g.U32(object + 0x3978);
  if (count && count <= 16 && g.Readable(cells, count * 24)) {
    for (uint32_t i = 0; i < count; ++i) {
      const uint32_t cell = cells + i * 24;
      if (g.U32(cell + 0x14)) continue;
      p.fuel += std::max(0.0f, g.F32(cell + 4));
      p.fuel_most += std::max(0.0f, g.F32(cell + 0xC));
    }
  }
  return p;
}

std::array<uint8_t, 3> Mix(std::array<uint8_t, 3> a, std::array<uint8_t, 3> b, float t) {
  t = std::clamp(t, 0.0f, 1.0f);
  return {uint8_t(a[0] + (b[0] - a[0]) * t), uint8_t(a[1] + (b[1] - a[1]) * t), uint8_t(a[2] + (b[2] - a[2]) * t)};
}

float Beat(uint64_t now, uint32_t period_ms) {
  return 0.5f + 0.5f * std::sin(float(now % period_ms) / float(period_ms) * 6.2831853f);
}

}  // namespace

void NotePlayerCreated(uint32_t player) { g_player.store(player, std::memory_order_release); }

GameOverlay::GameOverlay(rex::ui::ImGuiDrawer* drawer) : ImGuiDialog(drawer) {
  window_start_ns_ = rex::frame_stats::NowNs();
  window_frames_ = rex::frame_stats::g_presents.load(std::memory_order_acquire);
}

void GameOverlay::Sample() {
  const int64_t now = rex::frame_stats::NowNs();
  const uint64_t frames = rex::frame_stats::g_presents.load(std::memory_order_acquire);
  const int64_t span = now - window_start_ns_;
  if (span < 500'000'000) return;
  const uint64_t n = frames - window_frames_;
  fps_ = float(double(n) * 1e9 / double(span));
  ms_ = n ? float(double(span) / 1e6 / double(n)) : 0.0f;
  window_start_ns_ = now;
  window_frames_ = frames;
  // the slowest frames of the last few seconds: 1% low and the worst one
  const uint32_t count = uint32_t(std::min<uint64_t>(frames > 1 ? frames - 1 : 0, rex::frame_stats::kHistory));
  std::vector<uint32_t> times;
  times.reserve(count);
  for (uint32_t i = 0; i < count; ++i) {
    const uint32_t us = rex::frame_stats::g_history_us[(frames - 1 - i) % rex::frame_stats::kHistory].load(
        std::memory_order_relaxed);
    if (us) times.push_back(us);
  }
  if (times.empty()) {
    low_fps_ = worst_ms_ = 0;
    return;
  }
  std::sort(times.begin(), times.end());
  const uint32_t p99 = times[size_t(double(times.size() - 1) * 0.99)];
  low_fps_ = p99 ? float(1e6 / double(p99)) : 0.0f;
  worst_ms_ = float(times.back()) / 1000.0f;
}

void GameOverlay::Feedback() {
  namespace sony = rex::input::sony;
  auto& service = sony::GetService();
  const sony::Device device = service.ReadDevice(0);
  if (!device.generation) return;
  auto* kernel = REX_KERNEL_STATE();
  if (!kernel || !kernel->memory()) return;
  const Guest g{kernel->memory()};
  const uint64_t now = SDL_GetTicks();
  const Player p = ReadPlayer(g);

  // (always active, so the game's own rumble is never held back; with no player
  // character - the title screen, a loading screen - the light bar is the menus' blue)
  sony::GameState state{};
  state.active = true;
  state.player_identity = p.object;
  state.has_color = true;
  state.color = {40, 110, 255};
  if (p.valid) {
    if (p.object == player_) {
      // hit: the health dropped; repaired (Zandatsu, a nanopaste): it rose by a twentieth or more
      const int32_t drop = health_ - p.health;
      if (drop > 0) {
        service.Emit(0, device.generation, sony::Event::kDamage,
                     std::min(1.0f, 0.45f + 4.0f * float(drop) / float(p.most)), now);
        hit_until_ms_ = now + 220;
      } else if (-drop * 20 >= p.most) {
        heal_until_ms_ = now + 450;
      }
    }
    // the light bar: Raiden's blue with full health, to red as it runs out
    // (pulsing below a quarter); red for a hit, white for a repair; Ripper Mode
    // a deep red heartbeat
    const float ratio = std::clamp(float(p.health) / float(p.most), 0.0f, 1.0f);
    std::array<uint8_t, 3> color = Mix({255, 0, 0}, {60, 150, 255}, (ratio - 0.15f) / 0.75f);
    if (REXCVAR_GET(mgr_lightbar_effects)) {
      if (ratio < 0.25f) color = Mix({70, 0, 0}, {255, 0, 0}, Beat(now, 1000));
      if (p.ripper) color = Mix({110, 0, 10}, {255, 20, 40}, Beat(now, 600));
      if (now < heal_until_ms_) color = {220, 245, 255};
      if (now < hit_until_ms_) color = {255, 0, 0};
    }
    state.color = color;
    // the triggers: L2 (Blade Mode) heavier with fuel in the cells (heaviest in
    // Ripper Mode), R2 (Ninja Run) a light, steady pedal
    const float fuel = p.fuel_most > 0 ? std::clamp(p.fuel / p.fuel_most, 0.0f, 1.0f) : 0.0f;
    state.left_resistance = p.ripper ? 1.0f : 0.25f + 0.6f * fuel;
    state.right_resistance = 0.3f;
  }
  service.Publish(0, device.generation, state, now);
  player_ = p.valid ? p.object : 0;
  health_ = p.health;
}

// The quick menu's cheats (mgr_quick_menu.h), once a frame on the player character: its health back to its
// most, the fuel cells in use filled.
static void ApplyCheats() {
  const bool health = REXCVAR_GET(mgr_cheat_health), fuel = REXCVAR_GET(mgr_cheat_fuel);
  if (!health && !fuel) return;
  auto* kernel = REX_KERNEL_STATE();
  if (!kernel || !kernel->memory()) return;
  const Guest g{kernel->memory()};
  const Player p = ReadPlayer(g);
  if (!p.valid) return;
  if (health && p.health > 0 && p.health < p.most) g.Store32(p.object + 0x860, uint32_t(p.most));
  if (fuel) {
    const uint32_t cells = g.U32(p.object + 0x3970), count = g.U32(p.object + 0x3978);
    if (!count || count > 16 || !g.Readable(cells, count * 24)) return;
    for (uint32_t i = 0; i < count; ++i) {
      const uint32_t cell = cells + i * 24;
      if (g.U32(cell + 0x14)) continue;
      const float most = g.F32(cell + 0xC);
      if (most > 0 && g.F32(cell + 4) < most) g.Store32(cell + 4, g.U32(cell + 0xC));
    }
  }
}

void GameOverlay::OnDraw(ImGuiIO& io) {
  ApplyCheats();
  Feedback();
  const std::string mode = REXCVAR_GET(mgr_fps_counter);
  if (mode != "simple" && mode != "detailed") return;
  const bool simple = mode == "simple";
  Sample();
  const ImVec2 size = io.DisplaySize;
  const float s = std::min(size.x / 1920.0f, size.y / 1080.0f);
  ImDrawList* dl = ImGui::GetForegroundDrawList();
  ImFont* bold = MenuItemFont() ? MenuItemFont() : ImGui::GetFont();
  ImFont* body = MenuBodyFont() ? MenuBodyFont() : ImGui::GetFont();
  auto P = [&](float x, float y) { return ImVec2(x * s, y * s); };

  std::vector<std::string> info;
  if (!simple) info.push_back("1280x720  \xC2\xB7  60 FPS target");
  const float w = simple ? 196 : 264, pad = 12, line_h = 19;
  const float graph_h = simple ? 0 : 48;
  const float h = simple ? pad + 36 + pad - 4 : pad + 36 + 20 + float(info.size()) * line_h + 10 + graph_h + pad;
  const float x = 12, y = 12;
  dl->AddRectFilled(P(x, y), P(x + w, y + h), IM_COL32(0, 0, 0, 170), 8 * s);
  char big[16], unit[] = "FPS", ms[32], small[96];
  if (fps_ > 0) {
    std::snprintf(big, sizeof(big), "%.0f", fps_);
    std::snprintf(ms, sizeof(ms), "%.1f ms", ms_);
    std::snprintf(small, sizeof(small), "1%% low %.0f  \xC2\xB7  worst frame %.0f ms", low_fps_, worst_ms_);
  } else {
    std::snprintf(big, sizeof(big), "--");
    ms[0] = small[0] = 0;
  }
  const ImU32 col = fps_ > 0 ? RateColor(ms_) : IM_COL32(244, 245, 247, 255);
  const float big_size = 36 * s;
  const ImVec2 bsz = bold->CalcTextSizeA(big_size, 1e9f, 0, big);
  dl->AddText(bold, big_size, P(x + pad, y + pad - 5), col, big);
  dl->AddText(bold, 15 * s, ImVec2((x + pad) * s + bsz.x + 6 * s, (y + pad + 13) * s), IM_COL32(255, 255, 255, 170),
              unit);
  const ImVec2 msz = bold->CalcTextSizeA(20 * s, 1e9f, 0, ms);
  dl->AddText(bold, 20 * s, ImVec2((x + w - pad) * s - msz.x, (y + pad + 8) * s), IM_COL32(244, 245, 247, 255), ms);
  if (simple) return;
  dl->AddText(body, 14 * s, P(x + pad, y + pad + 37), IM_COL32(255, 255, 255, 175), small);
  for (size_t i = 0; i < info.size(); ++i)
    dl->AddText(body, 14 * s, P(x + pad, y + pad + 37 + 20 + float(i) * line_h), IM_COL32(255, 255, 255, 175),
                info[i].c_str());

  // the graph: one bar a frame, newest on the right, 0 to 66 ms (15 FPS) tall
  const float gx = x + pad, gy = y + pad + 36 + 20 + float(info.size()) * line_h + 10, gw = w - pad * 2;
  dl->AddRectFilled(P(gx, gy), P(gx + gw, gy + graph_h), IM_COL32(255, 255, 255, 18), 4 * s);
  constexpr float kTopMs = 66.7f;
  const uint64_t frames = rex::frame_stats::g_presents.load(std::memory_order_acquire);
  constexpr int kBars = 120;
  const float bar = gw / float(kBars);
  for (int i = 0; i < kBars && uint64_t(i) + 1 < frames; ++i) {
    const uint32_t us = rex::frame_stats::g_history_us[(frames - 1 - uint64_t(i)) % rex::frame_stats::kHistory].load(
        std::memory_order_relaxed);
    if (!us) continue;
    const float f_ms = float(us) / 1000.0f;
    const float bh = graph_h * std::min(f_ms, kTopMs) / kTopMs;
    const float bx = gx + gw - bar * float(i + 1);
    dl->AddRectFilled(P(bx, gy + graph_h - bh), P(bx + bar * 0.8f, gy + graph_h), RateColor(f_ms));
  }
  for (float line_ms : {16.7f, 33.3f}) {  // the 60 and 30 FPS marks, over the bars
    const float ly = gy + graph_h - graph_h * line_ms / kTopMs;
    dl->AddLine(P(gx, ly), P(gx + gw, ly), IM_COL32(0, 0, 0, 140), 2 * s);
    dl->AddLine(P(gx, ly), P(gx + gw, ly), IM_COL32(255, 255, 255, 90), 1 * s);
    const char* label = line_ms < 20 ? "60" : "30";
    dl->AddText(bold, 11 * s, P(gx + 3 + 1, ly - 13 + 1), IM_COL32(0, 0, 0, 200), label);
    dl->AddText(bold, 11 * s, P(gx + 3, ly - 13), IM_COL32(255, 255, 255, 200), label);
  }
}

void StartGameOverlay(rex::ui::ImGuiDrawer* drawer) {
  if (!g_overlay && drawer) g_overlay = std::make_unique<GameOverlay>(drawer);
}

}  // namespace mgrps5

#endif  // REX_PLATFORM_PS5
