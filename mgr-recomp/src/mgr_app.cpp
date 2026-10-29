// Metal Gear Rising: Revengeance - ReXGlue recompiled app (see mgr_app.h).
#include "mgr_app.h"

#include <system_error>

#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/platform.h>
#include <rex/system/kernel_state.h>

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
  // any of these to try another way.
  REXLOG_INFO("Metal Gear Rising: Revengeance: readback_resolve={} gpu_allow_invalid_fetch_constants={} "
              "render_target_path_vulkan={}",
              rex::cvar::GetFlagByName("readback_resolve"),
              rex::cvar::GetFlagByName("gpu_allow_invalid_fetch_constants"),
              rex::cvar::GetFlagByName("render_target_path_vulkan"));
}
