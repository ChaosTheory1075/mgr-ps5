// Metal Gear Rising: Revengeance - ReXGlue recompiled app (see mgr_app.h).
#include "mgr_app.h"

#include <cstdio>
#include <system_error>

#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/memory.h>
#include <rex/platform.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xthread.h>

#include "mgr_init.h"
#include "ps5/mgr_install.h"
#include "ps5/mgr_menu.h"
#include "ps5/mgr_trophies_game.h"

namespace fs = std::filesystem;

namespace {

#if REX_PLATFORM_PS5
const fs::path kAppRoot("/app0");
#endif

// The app's own folder: /app0 on the PS5, beside the program elsewhere.
fs::path AppRoot(const rex::PathConfig& defaults) {
#if REX_PLATFORM_PS5
  (void)defaults;
  return kAppRoot;
#else
  return defaults.config_path.parent_path();
#endif
}

fs::path g_app_root;

rex::PathConfig ResolvePaths(const rex::PathConfig& defaults);

}  // namespace

// The crash line's guest half (ps5_diag.cpp, patched in by ci/patch_framework.py):
// the faulting thread's volatile registers (kept in its context), LR, CTR, and
// its callers from the stack's back chain. Runs in the fault handler: no heap.
extern "C" int rex_guest_fault_report(char* out, int capacity) {
  auto* thread = rex::system::XThread::GetCurrentThread();
  if (!thread || !thread->thread_state() || !thread->thread_state()->context()) return 0;
  const auto* c = thread->thread_state()->context();
  int n = std::snprintf(out, size_t(capacity),
                        "thread %X lr %08X ctr %08X r1 %08X r3 %08X r4 %08X r5 %08X r6 %08X r7 %08X r8 %08X "
                        "r9 %08X r10 %08X r11 %08X r12 %08X | callers",
                        thread->handle(), uint32_t(c->lr), c->ctr.u32, c->r1.u32, c->r3.u32, c->r4.u32, c->r5.u32,
                        c->r6.u32, c->r7.u32, c->r8.u32, c->r9.u32, c->r10.u32, c->r11.u32, c->r12.u32);
  auto* kernel = REX_KERNEL_STATE();
  const uint32_t lo = thread->guest_stack_limit(), hi = thread->guest_stack_base();
  uint32_t sp = c->r1.u32;
  for (int i = 0; kernel && i < 16 && n > 0 && n < capacity - 12; ++i) {
    // (only inside this thread's stack: it's committed)
    if (sp < lo || sp + 4 > hi || (sp & 3)) break;
    const uint32_t back = rex::memory::load_and_swap<uint32_t>(kernel->memory()->TranslateVirtual(sp));
    if (back <= sp || back < lo + 8 || back > hi) break;
    const uint32_t lr = rex::memory::load_and_swap<uint32_t>(kernel->memory()->TranslateVirtual(back - 8));
    n += std::snprintf(out + n, size_t(capacity - n), " %08X", lr);
    sp = back;
  }
  return n;
}

std::unique_ptr<rex::ui::WindowedApp> MgrApp::Create(rex::ui::WindowedAppContext& ctx) {
  return std::unique_ptr<MgrApp>(new MgrApp(ctx, "mgr", PPCImageConfig));
}

std::optional<rex::PathConfig> MgrApp::OnFinalizePaths(const rex::PathConfig& defaults,
                                                       std::function<void(rex::PathConfig)> resume) {
#if REX_PLATFORM_PS5
  // The menu first (mgr_menu.cpp); PLAY carries on with the start.
  mgrps5::ShowMenu(imgui_drawer(), immediate_drawer(), AppRoot(defaults),
                   [defaults, resume](mgrps5::MenuChoice) { resume(ResolvePaths(defaults)); });
  return std::nullopt;
#else
  (void)resume;
  return ResolvePaths(defaults);
#endif
}

void MgrApp::OnConfigureFonts(ImFontAtlas* atlas) {
#if REX_PLATFORM_PS5
  mgrps5::ConfigureMenuFonts(atlas);
#else
  (void)atlas;
#endif
}

std::unique_ptr<rex::ui::AchievementNotificationDialog> MgrApp::CreateAchievementNotificationDialog() {
#if REX_PLATFORM_PS5
  // (an unlock as a PS5 trophy: ps5/mgr_trophies_game.h)
  return std::make_unique<mgrps5::TrophyPopup>(imgui_drawer(), immediate_drawer(), runtime());
#else
  return rex::ReXApp::CreateAchievementNotificationDialog();
#endif
}

void MgrApp::OnPostLaunchModule(rex::system::XThread* thread) {
  rex::ReXApp::OnPostLaunchModule(thread);
#if REX_PLATFORM_PS5
  // (saves the menu imported before the game made its profile folder: into it now)
  if (auto* kernel = REX_KERNEL_STATE(); kernel && kernel->user_profile() && !g_app_root.empty())
    mgrps5::install::PlacePendingSaves(g_app_root / "saves", kernel->user_profile()->xuid());
#endif
}

void MgrApp::OnPostSetup() {
#if REX_PLATFORM_PS5
  // The achievements' list and pictures, for the menu's Trophies page.
  if (runtime()) mgrps5::WriteTrophyCatalog(runtime(), runtime()->user_data_root());
#endif
}

namespace {

// The game's folders: game/ (the disc, with Title Update 4's default.xexp), its update/, dlc/ and saves/.
rex::PathConfig ResolvePaths(const rex::PathConfig& defaults) {
  auto paths = defaults;
  const fs::path root = AppRoot(defaults);
  std::error_code ec;
  g_app_root = root;
  if (paths.game_data_root.empty()) paths.game_data_root = root / "game";
  if (paths.update_data_root.empty() && fs::is_directory(paths.game_data_root / "update", ec))
    paths.update_data_root = paths.game_data_root / "update";
  if (paths.marketplace_content_root.empty()) paths.marketplace_content_root = root / "dlc";
  if (paths.saved_game_root.empty()) paths.saved_game_root = root / "saves";
  fs::create_directories(paths.saved_game_root, ec);
  fs::create_directories(paths.marketplace_content_root, ec);

  REXLOG_INFO("Metal Gear Rising: Revengeance: game {}, update {}, dlc {}, saves {}", paths.game_data_root.string(),
              paths.update_data_root.string(), paths.marketplace_content_root.string(),
              paths.saved_game_root.string());
  if (!fs::exists(paths.game_data_root / "default.xex", ec))
    REXLOG_ERROR("Metal Gear Rising: Revengeance: no default.xex in {} (install the game from the menu, see README.txt)",
                 paths.game_data_root.string());
  if (!fs::exists(paths.game_data_root / "default.xexp", ec))
    REXLOG_ERROR("Metal Gear Rising: Revengeance: no default.xexp in {} (Title Update 4's, from the menu)",
                 paths.game_data_root.string());
  return paths;
}

}  // namespace

void MgrApp::OnPreSetup(rex::RuntimeConfig& config) {
  // The generic Xenos GPU (Xenia's Vulkan backend): no game-specific renderer.
  if (!config.graphics && config.gpu_plugin.empty()) config.gpu_plugin = "xenos";
  // Xenia's defaults otherwise: Xenia Canary plays it with no issues
  // (xenia-canary/game-compatibility#645). mgr.toml beside eboot.bin can set
  // any of these to try another way. The title screen binds textures whose
  // fetch constants are typed "invalid" (all zero): drawn, as Xenia suggests,
  // instead of the draw being dropped.
  if (!rex::cvar::HasNonDefaultValue("gpu_allow_invalid_fetch_constants"))
    rex::cvar::SetLaunchFlag("gpu_allow_invalid_fetch_constants", "true");
  REXLOG_INFO("Metal Gear Rising: Revengeance: readback_resolve={} gpu_allow_invalid_fetch_constants={} "
              "render_target_path_vulkan={}",
              rex::cvar::GetFlagByName("readback_resolve"),
              rex::cvar::GetFlagByName("gpu_allow_invalid_fetch_constants"),
              rex::cvar::GetFlagByName("render_target_path_vulkan"));
}
