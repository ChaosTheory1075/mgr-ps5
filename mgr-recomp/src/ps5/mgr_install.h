// Metal Gear Rising: Revengeance RePlatinum (PS5) - the installer the menu's CONTENT and SAVES
// pages run (Crackdown PS5's cd_install, by way of Max Payne 3 RePrescribed's): what's
// in the app's install folder (<app>/install), what's installed, and the jobs
// that install, uninstall, import and back up, on a thread of their own.
//
//  - The disc: a disc image (.iso, any name) or a folder of its files
//    (anywhere in install/), into <app>/game (told by its default.xex's title
//    id).
//  - Title Update 4 (its package, any name): its default.xexp into game/, its
//    other files (patch_data/) into game/update/. Other title updates aren't
//    installed: the program is TU4's.
//  - The DLC packages (any number): each into <app>/dlc/<its content id>/,
//    the name the Xbox 360 gives it, whatever the file is called.
//  - Saves: Xbox 360 save packages, into <app>/saves the way the runtime keeps
//    them; and the app's own backups (install/backups/...), restored.
//
// Everything is found from what it is (an image's file system, a package's
// header), never from its name. An install is written next to its place and
// moved in when complete, so an interrupted one leaves nothing half done; the
// source is deleted once it's in. Archives (.7z, .rar, .zip) are listed to be
// extracted on a PC first.
#pragma once

#include <rex/platform.h>
#if REX_PLATFORM_PS5

#include <atomic>
#include <cstdint>
#include <filesystem>
#include <mutex>
#include <string>
#include <vector>

namespace mgrps5::install {

namespace fs = std::filesystem;

enum class Kind {
  kGameImage,    // a disc image
  kGameFolder,   // a folder with default.xex
  kUpdate,       // a title update (Title Update 4's is checked when it's installed)
  kDlc,
  kSave,         // an Xbox 360 save package
  kBackup,       // one of this app's backups
  kArchive,      // .7z / .rar / .zip: extract on a PC
  kOther,        // another game's package, or not known
};

struct Source {
  Kind kind = Kind::kOther;
  fs::path path;
  std::string label;  // for the menu
  bool installed = false;  // (kUpdate / kDlc) already installed from it: only to delete or keep
};

struct SaveInfo {
  std::string name;   // the save's folder (MP3_PROGRESSION, ...)
  int64_t modified = 0;  // (seconds since 1970)
};

struct Installed {
  bool game = false;    // game/
  bool update = false;  // Title Update 4 in it
  int dlc = 0;          // DLC packs in dlc/
  int saves = 0;
  std::vector<SaveInfo> save_list;  // (the newest first)
};

fs::path Folder(const fs::path& app);  // <app>/install (made if missing)
Installed Check(const fs::path& app);
std::vector<Source> Scan(const fs::path& app);
// The ones installed without being asked, as the menu opens: the disc, the title update, the DLC.
bool Automatic(Kind kind);

// The label of an Xbox 360 avatar item's package (Kind::kOther): the menu counts them in one line.
inline constexpr const char* kAvatarItemLabel = "avatar item";

enum class Remove { kGame, kUpdate, kDlc };

// One job at a time, on its own thread.
class Job {
 public:
  bool Busy() const { return busy_.load(std::memory_order_acquire); }
  // (0..1; with Busy)
  float Progress() const;
  std::string Title() const;
  // The last finished job's outcome ("" none yet) and whether it failed.
  std::string Result() const;
  bool Failed() const { return failed_.load(std::memory_order_acquire); }
  // Bumped when a job finishes (the menu looks at the folders again).
  uint32_t Generation() const { return generation_.load(std::memory_order_acquire); }

  bool Install(const fs::path& app, const Source& source);
  bool Uninstall(const fs::path& app, Remove what);
  bool Backup(const fs::path& app);

  // What the installs took from install/ (disc images, title update and DLC packages): kept there
  // until the user says to delete them (DeleteLeftovers) or to keep them (KeepLeftovers: noted in
  // install/kept.txt, so they aren't installed again).
  std::vector<fs::path> Leftovers() const;
  uint64_t LeftoverBytes() const;
  bool DeleteLeftovers(const fs::path& app);
  void KeepLeftovers(const fs::path& app);

 private:
  template <typename F>
  bool Start(std::string title, F&& work);

  std::atomic<bool> busy_{false}, failed_{false};
  std::atomic<uint32_t> generation_{0};
  std::atomic<uint64_t> done_{0}, total_{0};
  mutable std::mutex mutex_;
  std::string title_, result_;
  std::vector<fs::path> leftovers_;

 public:
  void Leftover(const fs::path& path);
};

Job& TheJob();

// The installer payload (mgr_install.cpp): one job run by it (kUnavailable:
// no payload loader), what it staged moved into place, a path as one inside the app's folder.
namespace payload {
enum class Ran { kUnavailable, kDone, kFailed };
inline constexpr const char* kJobRel = "UserData/mgr/.install-job";
inline constexpr const char* kStagingRel = "UserData/mgr/.install-staging";
Ran Run(const fs::path& app, const std::string& body, std::atomic<uint64_t>& done, std::atomic<uint64_t>& total,
        std::string& error);
bool Take(const fs::path& app, const std::string& rel, const fs::path& to, std::string& error);
std::string Inside(const fs::path& app, const fs::path& path);
inline fs::path JobFolder(const fs::path& app) { return app / kJobRel; }
}  // namespace payload

// Saves imported before the game made its profile folder wait in
// saves/_import/; at the game's start they move into saves/<profile>/.
void PlacePendingSaves(const fs::path& saves_root, uint64_t xuid);

}  // namespace mgrps5::install

#endif  // REX_PLATFORM_PS5
