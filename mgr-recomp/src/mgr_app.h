// Metal Gear Rising: Revengeance - ReXGlue recompiled app.
//
// On the PS5 the app folder is /app0 (the homebrew folder): the game's files
// in /app0/game (the disc's files, with Title Update 4's default.xexp beside
// default.xex), the title update's data in /app0/game/update, DLC packages in
// /app0/dlc and saves in /app0/saves. It opens on the menu (ps5/mgr_menu.h);
// achievements show as PS5 trophies (ps5/mgr_trophies.h).

#pragma once

#include <filesystem>
#include <functional>
#include <optional>

#include <rex/rex_app.h>

class MgrApp : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(rex::ui::WindowedAppContext& ctx);

 protected:
  std::optional<rex::PathConfig> OnFinalizePaths(const rex::PathConfig& defaults,
                                                 std::function<void(rex::PathConfig)> resume) override;
  void OnPreSetup(rex::RuntimeConfig& config) override;
  // The menu's UPSCALING and SHARPNESS, to the presenter (it read them before the menu).
  void ApplyUpscaling();
  void OnPostSetup() override;
  void OnPostLaunchModule(rex::system::XThread* thread) override;
  void OnConfigureFonts(ImFontAtlas* atlas) override;
  std::unique_ptr<rex::ui::AchievementNotificationDialog> CreateAchievementNotificationDialog() override;
};
