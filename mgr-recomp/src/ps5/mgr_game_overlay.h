// Metal Gear Rising: Revengeance RePlatinum (PS5) - what the app adds over the
// game while it runs (from gta4-ps5's game/ps5_overlay.h, as Max Payne 3 PS5's):
//
//  - the frame rate counter (SETTINGS > FPS COUNTER: simple, frames a second and
//    the frame time; detailed, also the slowest frames and a graph), on the left
//    edge halfway down, clear of the game's HUD in the corners;
//  - the DualSense's features, from the game's state each frame: the light bar
//    follows Raiden's health (blue when he's well, to red as it runs low, a
//    flash when he's hit, white as Zandatsu repairs him, deep red in Ripper
//    Mode), the adaptive triggers (L2, Blade Mode: a weight to pull, heavier
//    with fuel in the cells; R2, Ninja Run: a light pedal) and added rumble for
//    hits, over the game's own (rex::input::sony, which the PS5 controller
//    driver sends).
#pragma once

#include <rex/platform.h>
#if REX_PLATFORM_PS5

#include <cstdint>

#include <rex/ui/imgui_dialog.h>

namespace mgrps5 {

class GameOverlay final : public rex::ui::ImGuiDialog {
 public:
  explicit GameOverlay(rex::ui::ImGuiDrawer* drawer);

 protected:
  void OnDraw(ImGuiIO& io) override;
  // (drawn with each game frame, as gta4-ps5's: repainting every vblank queues
  // repeats ahead of the game's frames)
  bool WantsContinuousRepaint() const override { return false; }

 private:
  void Sample();
  void Feedback();

  // the counter: averaged over half a second
  uint64_t window_frames_ = 0;
  int64_t window_start_ns_ = 0;
  float fps_ = 0, ms_ = 0, low_fps_ = 0, worst_ms_ = 0;

  // the DualSense: what the last frame saw
  uint32_t player_ = 0;
  int32_t health_ = 0;
  uint64_t hit_until_ms_ = 0, heal_until_ms_ = 0;
};

// Put up over the game (MgrApp::OnPostSetup).
void StartGameOverlay(rex::ui::ImGuiDrawer* drawer);

// The player character (Raiden, or a DLC story's): each one the game makes,
// from its constructor (mgr_app.cpp), for the DualSense's features.
void NotePlayerCreated(uint32_t player);

}  // namespace mgrps5

#endif  // REX_PLATFORM_PS5
