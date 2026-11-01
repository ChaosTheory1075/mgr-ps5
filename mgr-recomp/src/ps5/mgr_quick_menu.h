// Metal Gear Rising: Revengeance RePlatinum (PS5) - the in-game quick menu (as Crackdown PS5's): L3 + R3
// together (both sticks pressed in) opens it over the game, for the cheats (infinite health, infinite fuel
// cells), the FPS counter and the DualSense's features, without going back to the app's menu. While it's
// open the game reads an idle controller; O (or L3 + R3 again) closes it. SETTINGS > CHEAT MENU turns it
// off (mgr_cheat_menu); what it changes is kept in menu.ini.
#pragma once

#include <rex/platform.h>
#if REX_PLATFORM_PS5

#include <cstdint>

#include <rex/ui/imgui_dialog.h>

namespace mgrps5 {

class QuickMenu final : public rex::ui::ImGuiDialog {
 public:
  explicit QuickMenu(rex::ui::ImGuiDrawer* drawer);

 protected:
  void OnDraw(ImGuiIO& io) override;
  // (every vblank only while it's open: drawn with the game's frames otherwise)
  bool WantsContinuousRepaint() const override;

 private:
  int row_ = 0;
  float shown_ = 0;  // 0..1, the fade
};

// Put up over the game (MgrApp::OnPostSetup).
void StartQuickMenu(rex::ui::ImGuiDrawer* drawer);

// One read of the controller by the game (the title's XInputGetState, mgr_app.cpp), on its thread: L3 + R3
// opens the menu, and while it's open the state the game gets is blanked.
void FilterPad(uint8_t* base, uint32_t state);

}  // namespace mgrps5

#endif  // REX_PLATFORM_PS5
