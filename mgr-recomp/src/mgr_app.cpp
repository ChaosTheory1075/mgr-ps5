// Metal Gear Rising: Revengeance - ReXGlue recompiled app (see mgr_app.h).
#include "mgr_app.h"

#include <cstdio>
#include <mutex>
#include <system_error>
#include <unordered_set>

#include <rex/cvar.h>
#include <rex/filesystem/devices/host_path_device.h>
#include <rex/filesystem/vfs.h>
#include <rex/logging.h>
#include <rex/memory.h>
#include <rex/platform.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xthread.h>

#include "mgr_init.h"
#include "ps5/mgr_game_overlay.h"
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
bool g_hd_movies = false;  // (the HD cutscenes: on, and movie_hd/ has movies: ResolvePaths)

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
  // The frame rate counter and the DualSense's features (ps5/mgr_game_overlay.h).
  mgrps5::StartGameOverlay(imgui_drawer());
#endif
  // HD cutscenes: the app's movie_hd/ as moviehd:\ (the kernel's NtCreateFile opens a cutscene's
  // movie from there when it has it: ci/patch_framework.py)
  if (g_hd_movies && REX_KERNEL_STATE()) {
    constexpr const char* kMount = "\\Device\\MgrMovieHd";
    auto device = std::make_unique<rex::filesystem::HostPathDevice>(kMount, g_app_root / "movie_hd", true);
    if (device->Initialize() && REX_KERNEL_FS()->RegisterDevice(std::move(device))) {
      REX_KERNEL_FS()->RegisterSymbolicLink("moviehd:", kMount);
      REXLOG_INFO("Metal Gear Rising: HD cutscenes from {}", (g_app_root / "movie_hd").string());
    } else {
      g_hd_movies = false;
      REXLOG_ERROR("Metal Gear Rising: couldn't mount {}", (g_app_root / "movie_hd").string());
    }
  }
}

// The player character's constructor (Pl0000's, which Raiden's and the DLC
// stories' classes start with: sub_822AA760, sub_822B2210, sub_822B9D30): the
// object, for the DualSense's light bar and triggers (mgr_game_overlay.cpp).
extern "C" void sub_822B4198(PPCContext& __restrict ctx, uint8_t* base) {
  const uint32_t player = ctx.r3.u32;
  __imp__sub_822B4198(ctx, base);
#if REX_PLATFORM_PS5
  mgrps5::NotePlayerCreated(player);
#endif
}

// Skip the startup logos. The boot loop (sub_82C00290) shows six logos (Konami,
// Kojima Productions, PlatinumGames, Havok, CRI, Dolby: logo\*.wtb, loaded by
// sub_82BFBF40) while the game loads, and carries on once both are done; the
// logos' update (sub_82BFCB68, once a frame: its "done" flag at +416) is told
// they're done, so the title comes as soon as the loading is.
REXCVAR_DEFINE_BOOL(mgr_skip_intro, true, "Metal Gear Rising", "Skip the logos at the start");

// HD cutscenes (the app's movie_hd/, opened in their place by the kernel's
// NtCreateFile: ci/patch_framework.py): their cut lists' PlayRate from 30 to 240,
// as the PC version's 60 fps pack sets it in its event files - the one value it
// changes in them. A cut list's MotionRate, PlayRate and the next value are read
// into three bytes (sub_8287D078: the object r3, PlayRate at +1).
REXCVAR_DEFINE_BOOL(mgr_hd_movies, true, "Metal Gear Rising",
                    "Play the cutscenes from the app's movie_hd/ when it has them (HD, 60 fps)");

extern "C" void sub_8287D078(PPCContext& __restrict ctx, uint8_t* base) {
  const uint32_t rates = ctx.r3.u32;
  __imp__sub_8287D078(ctx, base);
  if (g_hd_movies && REX_LOAD_U8(rates + 1) == 30) REX_STORE_U8(rates + 1, 240);
}

// A cutscene movie's playback memory. The movie object's start (sub_828CA630:
// the object r3, its CRI Mana player at +32, the memory at +40) sizes it from
// the movie's header and takes it from the object's heap (+12, sub_828E4648),
// which has room for the disc's 1024x576 movies and not for a 1080p one: the
// movie stops before its first frame and the cutscene is skipped. What the
// heap can't give comes from the system heap, given back before the object's
// release (sub_828CBE28) frees +40 through the heap's header at -4.
namespace {
thread_local bool g_movie_starting = false;
std::mutex g_movie_memory_mutex;
std::unordered_set<uint32_t> g_movie_memory;
}  // namespace

extern "C" void sub_828CA630(PPCContext& __restrict ctx, uint8_t* base) {
  const uint32_t movie = ctx.r3.u32;
  g_movie_starting = true;
  __imp__sub_828CA630(ctx, base);
  g_movie_starting = false;
  if (ctx.r3.u32 == 0) {
    REXLOG_WARN("Metal Gear Rising: a movie didn't start (state {}, picture {}x{})", REX_LOAD_U32(movie + 8),
                REX_LOAD_U32(movie + 64), REX_LOAD_U32(movie + 68));
  }
}

extern "C" void sub_828E4648(PPCContext& __restrict ctx, uint8_t* base) {
  if (!g_movie_starting) {
    __imp__sub_828E4648(ctx, base);
    return;
  }
  const uint32_t size = ctx.r4.u32;
  __imp__sub_828E4648(ctx, base);
  if (ctx.r3.u32) {
    REXLOG_INFO("Metal Gear Rising: a movie's playback memory: {} KB from the game's heap", size / 1024);
    return;
  }
  const uint32_t address = REX_KERNEL_MEMORY()->SystemHeapAlloc(size, 0x1000);
  REXLOG_INFO("Metal Gear Rising: a movie's playback memory: {} KB, more than the game's heap has; {}", size / 1024,
              address ? "from the system heap" : "the system heap hasn't room either");
  if (address) {
    std::lock_guard lock(g_movie_memory_mutex);
    g_movie_memory.insert(address);
  }
  ctx.r3.u64 = address;
}

extern "C" void sub_828CBE28(PPCContext& __restrict ctx, uint8_t* base) {
  const uint32_t memory = REX_LOAD_U32(ctx.r3.u32 + 40);
  if (memory) {
    std::unique_lock lock(g_movie_memory_mutex);
    if (g_movie_memory.erase(memory)) {
      lock.unlock();
      REX_STORE_U32(ctx.r3.u32 + 40, 0);
      REX_KERNEL_MEMORY()->SystemHeapFree(memory);
    }
  }
  __imp__sub_828CBE28(ctx, base);
}

// The CRI libraries' errors (sub_82664438: the message r4, its numbers r5-r7),
// in the log.
extern "C" void sub_82664438(PPCContext& __restrict ctx, uint8_t* base) {
  if (ctx.r4.u32) {
    const char* text = reinterpret_cast<const char*>(base + ctx.r4.u32);
    REXLOG_WARN("Metal Gear Rising: CRI: {:.200} ({} {} {})", text, int32_t(ctx.r5.u32), int32_t(ctx.r6.u32),
                int32_t(ctx.r7.u32));
  }
  __imp__sub_82664438(ctx, base);
}

extern "C" void sub_82BFCB68(PPCContext& __restrict ctx, uint8_t* base) {
  if (REXCVAR_GET(mgr_skip_intro)) {
    static bool logged = false;
    if (!logged) {
      logged = true;
      REXLOG_INFO("Metal Gear Rising: the startup logos skipped");
    }
    REX_STORE_U32(ctx.r3.u32 + 416, 1);
    return;
  }
  __imp__sub_82BFCB68(ctx, base);
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
  // HD cutscenes: movie_hd/'s movies (mounted in OnPostSetup; see sub_8287D078)
  int hd_movies = 0;
  for (const auto& e : fs::directory_iterator(root / "movie_hd", ec))
    if (e.path().extension() == ".usm" && e.file_size(ec) > 0) ++hd_movies;
  g_hd_movies = REXCVAR_GET(mgr_hd_movies) && hd_movies > 0;
  REXLOG_INFO("Metal Gear Rising: Revengeance: HD cutscenes {} ({} movies in movie_hd)", g_hd_movies ? "on" : "off",
              hd_movies);
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
  // The stall sampler (SIGPROF to every thread once no frame has come for 300
  // ms) is armed by the FPS counter's frame count, and froze Crackdown's loads.
  if (!rex::cvar::HasNonDefaultValue("ps5_hang_reports")) rex::cvar::SetLaunchFlag("ps5_hang_reports", "false");
  REXLOG_INFO("Metal Gear Rising: Revengeance: readback_resolve={} gpu_allow_invalid_fetch_constants={} "
              "render_target_path_vulkan={}",
              rex::cvar::GetFlagByName("readback_resolve"),
              rex::cvar::GetFlagByName("gpu_allow_invalid_fetch_constants"),
              rex::cvar::GetFlagByName("render_target_path_vulkan"));
}
