#!/usr/bin/env python3
"""Adapt a gta4-ps5 checkout to build Metal Gear Rising: Revengeance instead of GTA IV.

    patch_framework.py <gta4-ps5 checkout> [--host]

- glue/CMakeLists.txt adds mgr-recomp (copied in by the workflow) instead of
  gta4-recomp.
- src/graphics/CMakeLists.txt: on the PS5, the generic Xenos renderer
  (rexgpu-xenos) is built as a static library and linked in, and GTA IV's own
  renderer (rexgpu-gta4-native, its shader caches and FSR archive) is left out.
- src/filesystem/devices/disc_image_device.cpp includes direct_io.h on every
  non-Windows host (only the PS5 build had it).

Each edit checks that it applied, so a change upstream fails the build here
instead of somewhere later.
"""
import pathlib
import os
import re
import sys


def edit(path, old, new, count=1):
    text = path.read_text()
    if new in text:
        print(f"already  {path}")
        return
    if text.count(old) != count:
        if os.environ.get("PATCH_KEEP_GOING"):  # (to list every mismatch at once)
            print(f"MISMATCH {path.name}: {old[:150]!r}")
            return
        sys.exit(f"patch_framework: expected {count} of {old!r} in {path}, found {text.count(old)}")
    path.write_text(text.replace(old, new))
    print(f"patched  {path}")


def main():
    fw = pathlib.Path(sys.argv[1])
    sdk = fw / "glue" / "rexglue-sdk-main"

    edit(fw / "glue" / "CMakeLists.txt",
         'add_subdirectory("${REXSDK_DIR}/gta4-recomp" "${CMAKE_CURRENT_BINARY_DIR}/gta4-recomp")',
         'add_subdirectory("${REXSDK_DIR}/mgr-recomp" "${CMAKE_CURRENT_BINARY_DIR}/mgr-recomp")')

    gfx = sdk / "src" / "graphics" / "CMakeLists.txt"
    edit(gfx,
         "if(NOT PS5)\nadd_library(rexgpu-xenos SHARED\n",
         "if(PS5)\n"
         "# [mgr] the generic Xenos renderer, linked into the PS5 program\n"
         "add_library(rexgpu-xenos STATIC\n"
         "    plugin_main.cpp\n"
         "    ${REXGPU_XENOS_SOURCES}\n"
         ")\n"
         "add_library(rex::gpu-xenos ALIAS rexgpu-xenos)\n"
         "rexgpu_configure_plugin(rexgpu-xenos gpu-xenos)\n"
         "else()\n"
         "add_library(rexgpu-xenos SHARED\n")
    # GTA IV's renderer block: off for this game.
    edit(gfx,
         "if(REXGLUE_USE_VULKAN)\n    if(REXGLUE_BUILD_TESTS)\n",
         "if(REXGLUE_USE_VULKAN AND NOT MGR_NO_GTA4_NATIVE)\n    if(REXGLUE_BUILD_TESTS)\n")

    # STFS packages: a contiguous file's blocks follow one another, as the
    # Xbox 360 reads them; its hash entries' next-block links aren't needed.
    # The Blade Wolf DLC's are wrong partway through movie/evd020.usm (the
    # reader then asked for a hash table 4.7 GB into an 857 MB package), so
    # the walk only follows the links for fragmented files.
    edit(sdk / "src" / "filesystem" / "devices" / "stfs_container_device.cpp",
         "          remaining_size -= block_size;\n"
         "          auto block_hash = GetBlockHash(block_index);\n",
         "          remaining_size -= block_size;\n"
         "          if (dir_entry.flags.contiguous) {  // [mgr]\n"
         "            ++block_index;\n"
         "            continue;\n"
         "          }\n"
         "          auto block_hash = GetBlockHash(block_index);\n")

    # Bring-up: every file the game opens, and every one it looks for and
    # doesn't find, in the log (the game's data is a few CRI archives, so few
    # lines). The framework had them at debug and trace only.
    io = sdk / "src" / "kernel" / "xboxkrnl" / "xboxkrnl_io.cpp"
    edit(io,
         "    REXKRNL_DEBUG(\"[NtCreateFile] not found: path='{}' -> {:#x}\", target_path, result);\n",
         "    REXKRNL_INFO(\"[NtCreateFile] not found: path='{}' -> {:#x}\", target_path, result);  // [mgr]\n")
    edit(io,
         "    REXKRNL_IMPORT_RESULT(\"NtCreateFile\", \"{:#x} handle={:#x}\", result, handle);\n",
         "    REXKRNL_IMPORT_RESULT(\"NtCreateFile\", \"{:#x} handle={:#x}\", result, handle);\n"
         "    REXKRNL_INFO(\"[NtCreateFile] {} -> handle {:#x}\", target_path, handle);  // [mgr]\n")
    # HD cutscenes: a cutscene movie (...\movie\evXXXX.usm, the disc's or a DLC's) is opened
    # from moviehd:\ (the app's movie_hd/, mounted by mgr_app.cpp) when that folder has it - the
    # PC version's movies remastered to 1080p at 60 fps (Nexus Mods: MGRR FULLHD 60FPS
    # CUTSCENE UPSCALE), the same Sofdec video and ADX sound the 360's Mana plays. Empty files
    # (the pack's placeholders) are passed over. The cut lists' PlayRate goes with them
    # (mgr_app.cpp).
    edit(io,
         "#include <rex/filesystem/device.h>\n",
         "#include <cctype>\n#include <rex/cvar.h>\n#include <rex/filesystem/device.h>\n")
    edit(io,
         "u32 NtCreateFile_entry(mapped_u32 handle_out, u32 desired_access,\n",
         "namespace {\n"
         "// [mgr] moviehd:\\\\evXXXX.usm (the app's movie_hd/, mgr_app.cpp) for a cutscene movie's path\n"
         "// (empty: not one). mgr_hd_movies is the game's (mgr_app.cpp), looked up by name: the host\n"
         "// codegen tool links this file without the game.\n"
         "std::string MgrHdMoviePath(const std::string& path) {\n"
         "  std::string lower(path);\n"
         "  for (char& c : lower) c = char(std::tolower(static_cast<unsigned char>(c)));\n"
         "  const size_t name = lower.find_last_of(\"\\\\/\");\n"
         "  if (name == std::string::npos || name < 6 || lower.compare(name - 6, 6, \"\\\\movie\") != 0) return {};\n"
         "  if (lower.compare(name + 1, 2, \"ev\") != 0 || lower.size() < 4 ||\n"
         "      lower.compare(lower.size() - 4, 4, \".usm\") != 0) {\n"
         "    return {};\n"
         "  }\n"
         "  if (rex::cvar::GetFlagByName(\"mgr_hd_movies\") != \"true\") return {};\n"
         "  return \"moviehd:\\\\\" + path.substr(name + 1);\n"
         "}\n"
         "}  // namespace\n"
         "\n"
         "u32 NtCreateFile_entry(mapped_u32 handle_out, u32 desired_access,\n")
    edit(io,
         "  rex::filesystem::File* vfs_file;\n"
         "  rex::filesystem::FileAction file_action;\n"
         "  X_STATUS result = REX_KERNEL_FS()->OpenFile(\n"
         "      root_entry, target_path, rex::filesystem::FileDisposition((uint32_t)creation_disposition),\n"
         "      desired_access, (create_options & CreateOptions::FILE_DIRECTORY_FILE) != 0,\n"
         "      (create_options & CreateOptions::FILE_NON_DIRECTORY_FILE) != 0, &vfs_file, &file_action);\n",
         "  rex::filesystem::File* vfs_file;\n"
         "  rex::filesystem::FileAction file_action;\n"
         "  X_STATUS result = X_STATUS_UNSUCCESSFUL;\n"
         "  // [mgr] a cutscene movie: the HD one if it's there (see MgrHdMoviePath)\n"
         "  if (const std::string hd = MgrHdMoviePath(target_path); !hd.empty()) {\n"
         "    result = REX_KERNEL_FS()->OpenFile(nullptr, hd, rex::filesystem::FileDisposition::kOpen, desired_access,\n"
         "                                       false, true, &vfs_file, &file_action);\n"
         "    if (XSUCCEEDED(result) && (!vfs_file->entry() || !vfs_file->entry()->size())) {\n"
         "      vfs_file->Destroy();\n"
         "      result = X_STATUS_UNSUCCESSFUL;\n"
         "    }\n"
         "    REXKRNL_INFO(\"mgr: cutscene {} from {}\", target_path, XSUCCEEDED(result) ? hd : std::string(\"the disc\"));\n"
         "  }\n"
         "  if (!XSUCCEEDED(result))\n"
         "  result = REX_KERNEL_FS()->OpenFile(\n"
         "      root_entry, target_path, rex::filesystem::FileDisposition((uint32_t)creation_disposition),\n"
         "      desired_access, (create_options & CreateOptions::FILE_DIRECTORY_FILE) != 0,\n"
         "      (create_options & CreateOptions::FILE_NON_DIRECTORY_FILE) != 0, &vfs_file, &file_action);\n")

    # A guest crash's own state in the crash line: the app's
    # rex_guest_fault_report (mgr_app.cpp) writes the faulting thread's guest
    # registers and callers into a static buffer (no heap in the handler).
    diag = sdk / "src" / "core" / "ps5_diag.cpp"
    edit(diag, "struct RawLine {\n  char text[2048];\n", "struct RawLine {\n  char text[4096];  // [mgr] (with the guest's state)\n")
    edit(diag,
         "std::atomic<uint64_t> crashed_at_ms{0};\n",
         "std::atomic<uint64_t> crashed_at_ms{0};\n"
         "// [mgr] the faulting thread's guest state, from the app (no heap)\n"
         "extern \"C\" __attribute__((weak)) int rex_guest_fault_report(char* out, int capacity);\n")
    edit(diag,
         "  line.Add(\"\\n\");\n"
         "  const char* path = log_path[0] ? log_path : \"/app0/logs/crash.log\";\n",
         "  if (rex_guest_fault_report) {  // [mgr]\n"
         "    static char guest[1536];\n"
         "    if (rex_guest_fault_report(guest, int(sizeof(guest))) > 0) {\n"
         "      line.Add(\"\\n[ps5 crash] guest: \");\n"
         "      line.Add(guest);\n"
         "    }\n"
         "  }\n"
         "  line.Add(\"\\n\");\n"
         "  const char* path = log_path[0] ? log_path : \"/app0/logs/crash.log\";\n")

    # A thread created without a processor (proc_mask 0) stays on its
    # creator's hardware thread, as on the Xbox 360 ("all child threads stay
    # on the same hardware thread as the parent"), and the title's first
    # thread starts on hardware thread 0. The framework handed out 1, 2, ...
    # round-robin, the host's own threads included: the main thread came out
    # as 4, and Metal Gear Rising's job system, which maps hardware threads
    # 0, 1, 2, 3 and 5 to its workers (the PCR's current CPU at 0x10C), looked
    # up -1 for it and crashed before the title screen. (Only what the guest
    # sees: ignore_thread_affinities keeps the host's scheduling as it is.)
    edit(sdk / "src" / "system" / "xthread.cpp",
         "  if (!proc_mask) {\n"
         "    next_cpu = (next_cpu + 1) % 6;\n"
         "    return next_cpu;  // is this reasonable?\n",
         "  if (!proc_mask) {\n"
         "    // [mgr] the creator's hardware thread; 0 for the title's first thread\n"
         "    (void)next_cpu;\n"
         "    auto* creator = XThread::GetCurrentThread();\n"
         "    return (creator && creator->is_guest_thread()) ? creator->active_cpu() : 0;\n")

    # File writes from physical memory through the raw mapping, as the reads
    # already are (XFile::ReadInternalLocked): the guest's view of a physical
    # page can be protected for the GPU's write watches, which the host's
    # write() can't fault through as the game's own code does. Metal Gear
    # Rising builds its save in physical memory: its saves came out as mostly
    # zeros, and the game couldn't read them back ("Failed to read save data").
    edit(sdk / "src" / "system" / "xfile.cpp",
         "  size_t bytes_written = 0;\n"
         "  X_STATUS result = file_->WriteSync(\n"
         "      std::span<const uint8_t>(memory()->TranslateVirtual(buffer_guest_address), buffer_length),\n"
         "      size_t(byte_offset), &bytes_written);\n",
         "  size_t bytes_written = 0;\n"
         "  // [mgr] physical memory through the raw mapping (no GPU watch protection)\n"
         "  rex::memory::BaseHeap* write_heap = memory()->LookupHeap(buffer_guest_address);\n"
         "  const uint8_t* write_source =\n"
         "      write_heap && write_heap->heap_type() == memory::HeapType::kGuestPhysical\n"
         "          ? memory()->TranslatePhysical(\n"
         "                static_cast<rex::memory::PhysicalHeap*>(write_heap)->GetPhysicalAddress(buffer_guest_address))\n"
         "          : memory()->TranslateVirtual(buffer_guest_address);\n"
         "  X_STATUS result = file_->WriteSync(std::span<const uint8_t>(write_source, buffer_length),\n"
         "                                     size_t(byte_offset), &bytes_written);\n")

    # The physical pages' stale-protection recovery is right, but it logged
    # every one: 120,000 lines in a session (some 350 a second in play), each
    # a write to the log file from the faulting thread. The first 20, then a
    # count every 10,000.
    edit(sdk / "src" / "system" / "xmemory.cpp",
         "                               rex::memory::PageAccess::kReadWrite, nullptr)) {\n"
         "        REXSYS_WARN(\n",
         "                               rex::memory::PageAccess::kReadWrite, nullptr)) {\n"
         "        // [mgr] The page was protected because the GPU holds a copy of it\n"
         "        // (a texture): the write about to happen makes that copy stale, so\n"
         "        // the GPU is told, as TriggerCallbacks does for a watched page.\n"
         "        // Without it a video frame decoded through this alias never reached\n"
         "        // the screen: Metal Gear Rising's cutscene movies froze on a frame\n"
         "        // while their sound went on.\n"
         "        if (const uint32_t phys = GetPhysicalAddress(virtual_address); phys != UINT32_MAX) {\n"
         "          const uint32_t page = uint32_t(host_page_size);\n"
         "          auto invalidation_lock = global_critical_region_.Acquire();\n"
         "          for (auto callback : physical_memory_invalidation_callbacks_)\n"
         "            callback->first(callback->second, phys & ~(page - 1), page, true);\n"
         "        }\n"
         "        static std::atomic<uint64_t> recovered{0};  // [mgr]\n"
         "        const uint64_t n = ++recovered;\n"
         "        if (n % 10000 == 0) REXSYS_INFO(\"Recovered stale physical page protection: {} times\", n);\n"
         "        if (n <= 20) REXSYS_WARN(\n")

    # Cutscene movies (CRI Sofdec, decoded by the CPU into the same few
    # textures every frame) froze for up to 9 s while their sound went on:
    # the frames reached the GPU only when a write watch happened to fire or
    # the stale page scan (128 pages a frame: all memory in about 8.5 s at
    # 30 FPS) came round to them. mgr_004.log: the title movie's planes
    # reloaded every frame on its first showing, and the scan found the
    # cutscene movie's pages (08B74000-08B7C000) changed with no watch fired.
    # Whatever leaves a page unwatched (the 16 KB host pages hold four guest
    # pages, the E0 view is 4 KB off the others, the hot page list fills), a
    # texture the CPU rewrites no longer depends on the watches: the first
    # draw of each frame that binds it compares its pages with the hashes
    # taken at their upload, and a changed page is invalidated as a fired
    # watch would, so the texture is reloaded for that draw. Checked: linear
    # textures (the movie's planes; the game's other textures are tiled) and
    # textures on pages the CPU changed in the last 300 frames; at most 16 MB
    # hashed a frame.
    sm_h = sdk / "include" / "rex" / "graphics" / "shared_memory.h"
    edit(sm_h,
         """  uint32_t CheckStalePages(uint32_t pages_per_frame);
""",
         """  uint32_t CheckStalePages(uint32_t pages_per_frame);

  // [mgr] The pages of a texture's range compared with their hashes taken at upload (once a
  // frame a texture, from TextureCache::RequestTextures); a changed page is invalidated as a
  // fired write watch would. always: checked even if the CPU didn't change its pages lately.
  // Returns whether any page was invalidated.
  bool CheckDynamicRange(uint32_t start, uint32_t length, bool always);
  uint32_t frame() const { return hot_frame_.load(std::memory_order_relaxed); }
  // [mgr] A linear texture (a movie frame's plane): its guest data hashed (the movie log), and
  // its range invalidated so that it's reloaded from guest memory, whatever the watches say.
  uint64_t HashGuestRange(uint32_t start, uint32_t length);
  void InvalidateRangeNow(uint32_t start, uint32_t length);
""")
    edit(sm_h,
         """  std::vector<uint32_t> hot_page_checked_batch_;
""",
         """  std::vector<uint32_t> hot_page_checked_batch_;
  // [mgr] CheckDynamicRange's budget
  static constexpr uint32_t kDynamicCheckBytesPerFrame = 16u << 20;
  uint32_t dynamic_check_frame_ = 0;
  uint32_t dynamic_check_bytes_ = 0;
""")
    edit(sdk / "src" / "graphics" / "shared_memory.cpp",
         """namespace {
thread_local bool invalidation_from_write = false;  // [crackdown]
""",
         """bool SharedMemory::CheckDynamicRange(uint32_t start, uint32_t length, bool always) {
  // [mgr]
  if (!length || start >= kBufferSize || page_hashes_.size() != (kBufferSize >> page_size_log2_)) {
    return false;
  }
  const uint32_t page_size = uint32_t(1) << page_size_log2_;
  const uint32_t frame = hot_frame_.load(std::memory_order_relaxed);
  const uint32_t page_first = start >> page_size_log2_;
  const uint32_t page_last = std::min(uint32_t((uint64_t(start) + length - 1) >> page_size_log2_),
                                      uint32_t(page_hashes_.size() - 1));
  if (!always) {
    bool recent = false;
    for (uint32_t page = page_first; page <= page_last && !recent; ++page) {
      const uint32_t last = page_invalidation_frame_[page];
      recent = last && frame - last <= kHotPageQuietFrames;
    }
    if (!recent) {
      return false;
    }
  }
  if (dynamic_check_frame_ != frame) {
    dynamic_check_frame_ = frame;
    dynamic_check_bytes_ = 0;
  }
  bool invalidated = false;
  for (uint32_t page = page_first; page <= page_last; ++page) {
    if (dynamic_check_bytes_ >= kDynamicCheckBytesPerFrame) {
      break;
    }
    const uint64_t stored = page_hashes_[page];
    if (!stored) {
      continue;
    }
    const uint32_t address = page << page_size_log2_;
    const uint32_t block = page >> 6;
    const uint64_t bit = uint64_t(1) << (page & 63);
    {
      // (as CheckStalePages: a valid page is committed; GPU-written ones and those the guest made
      // unreadable are left alone)
      auto global_lock = global_critical_region_.Acquire();
      const uint64_t* valid_flags = active_valid_flags_.load(std::memory_order_relaxed);
      if (!valid_flags || !(valid_flags[block] & bit) ||
          (system_page_flags_valid_and_gpu_written_[block] & bit)) {
        continue;
      }
      uint32_t protect = 0;
      auto* physical_heap = memory_.GetPhysicalHeap();
      if (!physical_heap || !physical_heap->QueryProtect(address, &protect) ||
          !(protect & memory::kMemoryProtectRead)) {
        continue;
      }
      dynamic_check_bytes_ += page_size;
      if (XXH3_64bits(memory_.TranslatePhysical(address), page_size) == stored) {
        continue;
      }
    }
    page_hashes_[page] = 0;
    memory_.TriggerPhysicalMemoryCallbacks(rex::thread::global_critical_region::AcquireDirect(),
                                           0xA0000000u + address, page_size, true, true);
    memory_.TriggerPhysicalMemoryCallbacks(rex::thread::global_critical_region::AcquireDirect(),
                                           0xC0000000u + address, page_size, true, true);
    if (address >= 0x1000) {
      memory_.TriggerPhysicalMemoryCallbacks(rex::thread::global_critical_region::AcquireDirect(),
                                             0xE0000000u + address - 0x1000, page_size, true, true);
    }
    MemoryInvalidationCallback(address, page_size, true);
    invalidated = true;
  }
  if (invalidated) {
    static std::atomic<uint64_t> dynamic_reloads{0};
    const uint64_t n = ++dynamic_reloads;
    if (n <= 5 || !(n & (n - 1))) {
      REXGPU_INFO("mgr: a CPU-written texture at {:08X} changed with no write watch fired ({} so far)",
                  start, n);
    }
  }
  return invalidated;
}

uint64_t SharedMemory::HashGuestRange(uint32_t start, uint32_t length) {
  // [mgr]
  if (!length || start >= kBufferSize) {
    return 0;
  }
  length = std::min(length, kBufferSize - start);
  return XXH3_64bits(memory_.TranslatePhysical(start), length);
}

void SharedMemory::InvalidateRangeNow(uint32_t start, uint32_t length) {
  // [mgr] (as CheckStalePages does for a changed page, each physical view's watches included)
  if (!length || start >= kBufferSize) {
    return;
  }
  length = std::min(length, kBufferSize - start);
  const uint32_t page_size = uint32_t(1) << page_size_log2_;
  const uint32_t first = start & ~(page_size - 1);
  const uint32_t size = ((start + length - first) + page_size - 1) & ~(page_size - 1);
  for (uint32_t page = first >> page_size_log2_; page < ((first + size) >> page_size_log2_) &&
                                                 page < page_hashes_.size();
       ++page) {
    page_hashes_[page] = 0;
  }
  memory_.TriggerPhysicalMemoryCallbacks(rex::thread::global_critical_region::AcquireDirect(),
                                         0xA0000000u + first, size, true, true);
  memory_.TriggerPhysicalMemoryCallbacks(rex::thread::global_critical_region::AcquireDirect(),
                                         0xC0000000u + first, size, true, true);
  if (first >= 0x1000) {
    memory_.TriggerPhysicalMemoryCallbacks(rex::thread::global_critical_region::AcquireDirect(),
                                           0xE0000000u + first - 0x1000, size, true, true);
  }
  MemoryInvalidationCallback(first, size, true);
}

namespace {
thread_local bool invalidation_from_write = false;  // [crackdown]
""")
    tc_h = sdk / "include" / "rex" / "graphics" / "pipeline" / "texture" / "cache.h"
    edit(tc_h,
         """    void MakeUpToDateAndWatch(const rex::thread::global_lock_t& global_lock);
""",
         """    void MakeUpToDateAndWatch(const rex::thread::global_lock_t& global_lock);
    // [mgr] the frame its pages were last compared with their upload hashes; a linear one's data
    // hash then (the movie log)
    uint32_t dynamic_check_frame = 0;
    uint64_t dynamic_content_hash = 0;
""")
    edit(tc_h,
         """  uint64_t current_submission_index_ = 0;
""",
         """  uint64_t current_submission_index_ = 0;
  uint32_t dynamic_check_frame_ = 0;  // [mgr]
""")
    tc = sdk / "src" / "graphics" / "pipeline" / "texture" / "cache.cpp"
    # The movie log: each second a linear texture is drawn, how many frames drew it and in how
    # many of them the game had written new data into it. A freeze with new data each frame is
    # the GPU's side; one with none, the game's (its decoder or its clock).
    edit(tc,
         """void TextureCache::RequestTextures(uint32_t used_texture_mask) {
""",
         """namespace {
// [mgr] the movie log
struct MovieLogEntry {
  uint32_t base = 0, frames = 0, changed = 0, last_frame = 0;
};
MovieLogEntry g_movie_log[8];
std::chrono::steady_clock::time_point g_movie_log_time;
void MovieLogFrame(uint32_t base, uint32_t frame, bool changed) {
  const auto now = std::chrono::steady_clock::now();
  if (now - g_movie_log_time >= std::chrono::seconds(1)) {
    std::string line;
    for (MovieLogEntry& e : g_movie_log) {
      if (e.frames) {
        line += fmt::format(" {:08X}: {} new of {}", e.base, e.changed, e.frames);
      }
      e = MovieLogEntry();
    }
    if (!line.empty()) {
      REXGPU_INFO("mgr movie 1 s (linear textures: frames with new data of frames drawn):{}", line);
    }
    g_movie_log_time = now;
  }
  MovieLogEntry* slot = nullptr;
  for (MovieLogEntry& e : g_movie_log) {
    if (e.frames && e.base == base) {
      slot = &e;
      break;
    }
    if (!slot && !e.frames) {
      slot = &e;
    }
  }
  if (!slot || slot->last_frame == frame + 1) {
    return;
  }
  slot->base = base;
  slot->last_frame = frame + 1;
  ++slot->frames;
  slot->changed += changed ? 1 : 0;
}
}  // namespace

void TextureCache::RequestTextures(uint32_t used_texture_mask) {
""")
    edit(tc, "#include <mutex>\n", "#include <chrono>\n#include <mutex>\n#include <string>\n\n#include <fmt/format.h>\n")
    edit(tc,
         """    ResetTextureBindings();
  }

  // Update the texture keys and the textures.
""",
         """    ResetTextureBindings();
  }

  // [mgr] each frame's first draws look at every binding again (CheckDynamicRange)
  const uint32_t dynamic_frame = shared_memory().frame();
  if (dynamic_frame != dynamic_check_frame_) {
    dynamic_check_frame_ = dynamic_frame;
    texture_bindings_in_sync_ = 0;
  }

  // Update the texture keys and the textures.
""")
    edit(tc,
         """    if (g_before_texture_read) {
      Texture* loading = load_unsigned_data ? binding.texture
""",
         """    // [mgr] a texture the CPU rewrites (a cutscene movie's frame): its pages compared with their
    // upload hashes once a frame, reloaded if they changed with no write watch fired
    for (Texture* dynamic : {binding.texture, binding.texture_signed}) {
      if (!dynamic || dynamic->dynamic_check_frame == dynamic_frame ||
          (dynamic->outdated_mask() & Texture::kOutdatedBitBase)) {
        continue;
      }
      dynamic->dynamic_check_frame = dynamic_frame;
      const TextureKey dynamic_key = dynamic->key();
      if (dynamic_key.scaled_resolve || !dynamic->GetGuestBaseSize()) {
        continue;
      }
      if (!dynamic_key.tiled) {
        // [mgr] a linear texture (the movie's planes): reloaded every frame, and whether its data
        // changed counted for the movie log
        const uint32_t base = dynamic_key.base_page << 12;
        const uint64_t hash = shared_memory().HashGuestRange(base, dynamic->GetGuestBaseSize());
        MovieLogFrame(base, dynamic_frame, hash != dynamic->dynamic_content_hash);
        dynamic->dynamic_content_hash = hash;
        shared_memory().InvalidateRangeNow(base, dynamic->GetGuestBaseSize());
        (dynamic == binding.texture ? load_unsigned_data : load_signed_data) = true;
        continue;
      }
      if (shared_memory().CheckDynamicRange(dynamic_key.base_page << 12, dynamic->GetGuestBaseSize(),
                                            !dynamic_key.tiled)) {
        (dynamic == binding.texture ? load_unsigned_data : load_signed_data) = true;
      }
    }
    if (g_before_texture_read) {
      Texture* loading = load_unsigned_data ? binding.texture
""")

    # NtReadFile on an asynchronous file (opened without FILE_SYNCHRONOUS_IO)
    # returns STATUS_PENDING, its outcome in the I/O status block, as Xenia's
    # and NtWriteFile here do - also when the read was done on the spot. The
    # fork returned STATUS_SUCCESS then: Metal Gear Rising's save loading
    # takes only the pending path as a read, and showed "Failed to read save
    # data" for every save.
    edit(io,
         "    completion.Complete(result, bytes_read);\n"
         "    REXKRNL_IMPORT_RESULT(\n"
         "        \"NtReadFile\", \"{:#x} inline=1 synchronous={} completion_port={} wait={} transferred={}\",\n"
         "        result, file->is_synchronous(), has_completion_port, ev ? \"event\" : \"file\", bytes_read);\n"
         "    return result;\n",
         "    completion.Complete(result, bytes_read);\n"
         "    REXKRNL_IMPORT_RESULT(\n"
         "        \"NtReadFile\", \"{:#x} inline=1 synchronous={} completion_port={} wait={} transferred={}\",\n"
         "        result, file->is_synchronous(), has_completion_port, ev ? \"event\" : \"file\", bytes_read);\n"
         "    if (XSUCCEEDED(result) && !file->is_synchronous()) return X_STATUS_PENDING;  // [mgr]\n"
         "    return result;\n")

    # XamSwapDisc reaches an app that defines rex_app_swap_disc (Max Payne 3's
    # disc 2); without one (this game has one disc), the stub as before.
    xam_info = sdk / "src" / "kernel" / "xam" / "xam_info.cpp"
    edit(xam_info,
         "u32 XamSwapDisc_entry(u32 disc_number) {\n",
         "extern \"C\" __attribute__((weak)) void rex_app_swap_disc(uint32_t disc_number);\n\n"
         "u32 XamSwapDisc_entry(u32 disc_number) {\n"
         "  REXKRNL_INFO(\"XamSwapDisc({})\", (uint32_t)disc_number);\n"
         "  if (rex_app_swap_disc) rex_app_swap_disc(disc_number);\n")
    # The game's file reads, in the log (the telemetry was only printed on
    # Android): every 10 s while it reads, how much and how long a read took,
    # for reports of slow loading.
    xio = sdk / "src" / "kernel" / "xboxkrnl" / "xboxkrnl_io.cpp"
    edit(xio,
         "  if (now - last > 2000000000ll && t.last_report_ns.compare_exchange_strong(last, now)) {\n",
         "  if (now - last > 10000000000ll && t.last_report_ns.compare_exchange_strong(last, now)) {\n")
    edit(xio,
         "                        (long long)peak);\n#endif\n",
         "                        (long long)peak);\n#endif\n"
         "    if (last) {  // [mgr]\n"
         "      const double secs = double(now - last) / 1e9;\n"
         "      REXKRNL_INFO(\"mgr io: {:.0f} reads/s ({} async), {:.1f} MB/s, {:.0f} KB a read, {:.2f} ms a read, \"\n"
         "                   \"{} at once at most\",\n"
         "                   reads / secs, async_reads, total / 1e6 / secs, reads ? total / 1024.0 / reads : 0.0,\n"
         "                   reads ? service / 1e6 / reads : 0.0, peak);\n"
         "    }\n")
    # XGetLanguage returned English whatever user_language said (the Xbox 360's
    # console language, which the game's text and trophies follow): the
    # menu's LANGUAGE setting sets it (mgr_menu.cpp).
    edit(xam_info,
         "#include <rex/system/kernel_state.h>\n",
         "#include <rex/system/flags.h>\n#include <rex/system/kernel_state.h>\n")
    edit(xam_info,
         "u32 XGetLanguage_entry() {\n",
         "u32 XGetLanguage_entry() {\n"
         "  if (const uint32_t language = REXCVAR_GET(user_language); language >= 1 && language <= 12)\n"
         "    return language;\n")

    # HD texture replacement in the Vulkan texture cache (ci/fw-files/
    # src/graphics/vulkan/hd_textures.cpp): its members, and three hooks.
    files = pathlib.Path(__file__).resolve().parent / "fw-files"
    for f in files.rglob("*"):
        if f.is_file():
            dst = sdk / f.relative_to(files)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(f.read_bytes())
            print(f"copied   {dst}")
    edit(gfx,
         "    vulkan/texture_cache.cpp\n",
         "    vulkan/texture_cache.cpp\n    vulkan/hd_textures.cpp\n")
    # [mgr] Max Payne 3 RePrescribed's (its 1.0.5): the presenter for FSR 1, SMAA 1x.
    # The graphics system (its presenter), for the app: the menu's UPSCALING
    # setting goes to the presenter, which took present_effect at its start,
    # before the menu (mgr_app.cpp).
    edit(sdk / "include" / "rex" / "rex_app.h",
         "  ui::Window* window() const { return window_.get(); }\n",
         "  ui::Window* window() const { return window_.get(); }\n"
         "  system::IGraphicsSystem* graphics_system() const { return config_.graphics.get(); }  // [mp3]\n")
    # SMAA 1x as a swap post effect (swap_post_effect smaa: ci/fw-files/src/graphics/vulkan/
    # mp3_smaa.cpp, shaders from tools/smaa). It runs where FXAA does, on the same gamma-corrected
    # source image, before the presenter's upscaling (FSR 1): SMAA cleans the edges with less blur
    # than FXAA, so the upscaler doesn't enlarge the jaggies. FXAA stays the fallback.
    edit(sdk / "include" / "rex" / "graphics" / "command_processor.h",
         "    kFxaaExtreme,\n  };\n",
         "    kFxaaExtreme,\n    kSmaa,  // [mp3]\n  };\n")
    edit(sdk / "src" / "graphics" / "graphics_system.cpp",
         "    .allowed({\"none\", \"fxaa\", \"fxaa_extreme\"})\n",
         "    .allowed({\"none\", \"fxaa\", \"fxaa_extreme\", \"smaa\"})  // [mp3]\n")
    edit(sdk / "src" / "graphics" / "graphics_system.cpp",
         "  if (lowered == \"fxaa_extreme\" || lowered == \"extreme\") {\n",
         "  if (lowered == \"smaa\") {  // [mp3]\n"
         "    return rex::graphics::CommandProcessor::SwapPostEffect::kSmaa;\n"
         "  }\n"
         "  if (lowered == \"fxaa_extreme\" || lowered == \"extreme\") {\n")
    vcph_smaa = sdk / "include" / "rex" / "graphics" / "vulkan" / "command_processor.h"
    edit(vcph_smaa,
         "  void BindExternalComputePipeline(VkPipeline pipeline);\n",
         "  void BindExternalComputePipeline(VkPipeline pipeline);\n"
         "  // [mp3] SMAA (mp3_smaa.cpp): false if unavailable (FXAA then).\n"
         "  bool Mp3SmaaRecord(VkImageView color_view, VkImage dest_image, VkImageView dest_view,\n"
         "                     uint32_t width, uint32_t height, uint32_t frame_index);\n"
         "  bool Mp3SmaaInitialize();\n"
         "  void Mp3SmaaShutdown();\n")
    edit(vcph_smaa,
         "  VkImageLayout swap_fxaa_source_layout_ = VK_IMAGE_LAYOUT_UNDEFINED;\n",
         "  VkImageLayout swap_fxaa_source_layout_ = VK_IMAGE_LAYOUT_UNDEFINED;\n"
         "  struct Mp3Smaa;\n"
         "  Mp3Smaa* mp3_smaa_ = nullptr;  // [mp3] created on first use\n")
    vcp_smaa = sdk / "src" / "graphics" / "vulkan" / "command_processor.cpp"
    edit(vcp_smaa,
         "        bool use_fxaa = swap_post_effect == SwapPostEffect::kFxaa ||\n"
         "                        swap_post_effect == SwapPostEffect::kFxaaExtreme;\n",
         "        bool use_fxaa = swap_post_effect == SwapPostEffect::kFxaa ||\n"
         "                        swap_post_effect == SwapPostEffect::kFxaaExtreme ||\n"
         "                        swap_post_effect == SwapPostEffect::kSmaa;  // [mp3] FXAA's source image\n")
    edit(vcp_smaa,
         "            BindExternalComputePipeline(swap_post_effect == SwapPostEffect::kFxaaExtreme\n"
         "                                            ? swap_fxaa_extreme_pipeline_\n"
         "                                            : swap_fxaa_pipeline_);\n"
         "            deferred_command_buffer_.CmdVkDispatch(group_count_x, group_count_y, 1);\n",
         "            if (swap_post_effect != SwapPostEffect::kSmaa ||\n"
         "                !Mp3SmaaRecord(swap_fxaa_source_image_view_, vulkan_context.image(),\n"
         "                               vulkan_context.image_view(), guest_output_width,\n"
         "                               guest_output_height, swap_frame_index)) {  // [mp3]\n"
         "              BindExternalComputePipeline(swap_post_effect == SwapPostEffect::kFxaaExtreme\n"
         "                                              ? swap_fxaa_extreme_pipeline_\n"
         "                                              : swap_fxaa_pipeline_);\n"
         "              deferred_command_buffer_.CmdVkDispatch(group_count_x, group_count_y, 1);\n"
         "            }\n")
    edit(vcp_smaa,
         "void VulkanCommandProcessor::ShutdownContext() {\n"
         "  GpuLane::Get().Drain();  // [crackdown]\n"
         "  AwaitAllQueueOperationsCompletion();\n",
         "void VulkanCommandProcessor::ShutdownContext() {\n"
         "  GpuLane::Get().Drain();  // [crackdown]\n"
         "  AwaitAllQueueOperationsCompletion();\n"
         "  Mp3SmaaShutdown();  // [mp3]\n")
    edit(gfx,
         "    vulkan/texture_cache.cpp\n    vulkan/hd_textures.cpp\n",
         "    vulkan/texture_cache.cpp\n    vulkan/hd_textures.cpp\n    vulkan/mp3_smaa.cpp\n")
    tc_h = sdk / "include" / "rex" / "graphics" / "vulkan" / "texture_cache.h"
    edit(tc_h,
         "class VulkanTextureCache final : public TextureCache {\n",
         "struct HdReplacement;\nstruct HdReplacer;\nstruct HdDds;\n\n"
         "class VulkanTextureCache final : public TextureCache {\n")
    edit(tc_h,
         "    VkImage image() const { return image_; }\n",
         "    VkImage image() const { return image_; }\n\n"
         "    // HD textures (hd_textures.cpp): the replacement this texture's views come from.\n"
         "    std::shared_ptr<HdReplacement> hd_replacement;\n"
         "    uint64_t hd_pending = 0;  // (the replacement being read in)\n"
         "    uint64_t hd_last_load = 0;  // (submission)\n"
         "    uint8_t hd_fast_reloads = 0;\n"
         "    uint64_t hd_head = 0;  // (its data's first 4 KB when it was last hashed)\n"
         "    uint64_t hd_seen_head = 0;  // (and at its last load)\n"
         "    friend class VulkanTextureCache;\n")
    edit(tc_h,
         "  std::pair<uint64_t, uint64_t> scaled_resolve_last_written_range_{0, 0};\n};\n",
         "  std::pair<uint64_t, uint64_t> scaled_resolve_last_written_range_{0, 0};\n\n"
         "  // HD textures (hd_textures.cpp)\n"
         "  HdReplacer* Hd() const;\n"
         "  void HdBeginSubmission();\n"
         "  void HdAfterLoad(VulkanTexture& texture, bool load_base);\n"
         "  std::shared_ptr<HdReplacement> HdLoad(uint64_t hash);\n"
         "  std::shared_ptr<HdReplacement> HdUpload(uint64_t hash, HdDds& dds);\n"
         "  void HdPoll();\n"
         "  VkImageView HdView(VulkanTexture& texture, bool is_signed, uint32_t host_swizzle, bool is_array) const;\n"
         "  mutable HdReplacer* hd_ = nullptr;\n"
         "  mutable bool hd_disabled_ = false;\n};\n")
    tc = sdk / "src" / "graphics" / "vulkan" / "texture_cache.cpp"
    edit(tc,
         "  TextureCache::RequestTextures(used_texture_mask);\n",
         "  HdPoll();\n  TextureCache::RequestTextures(used_texture_mask);\n")
    edit(tc,
         "  TextureCache::BeginSubmission(new_submission_index);\n",
         "  TextureCache::BeginSubmission(new_submission_index);\n  HdBeginSubmission();\n")
    edit(tc,
         "    copy_region.imageExtent.depth = std::max(depth >> level, UINT32_C(1));\n  }\n\n  return true;\n}\n",
         "    copy_region.imageExtent.depth = std::max(depth >> level, UINT32_C(1));\n  }\n\n"
         "  HdAfterLoad(vulkan_texture, load_base);\n  return true;\n}\n")
    edit(tc,
         "VkImageView VulkanTextureCache::VulkanTexture::GetView(bool is_signed, uint32_t host_swizzle,\n"
         "                                                       bool is_array) {\n",
         "VkImageView VulkanTextureCache::VulkanTexture::GetView(bool is_signed, uint32_t host_swizzle,\n"
         "                                                       bool is_array) {\n"
         "  if (hd_replacement) {\n"
         "    const auto& cache = static_cast<const VulkanTextureCache&>(texture_cache());\n"
         "    if (VkImageView view = cache.HdView(*this, is_signed, host_swizzle, is_array)) return view;\n"
         "  }\n")

    # REX_DUMP_IMAGE=<file>: codegen writes the loaded (decrypted) image
    # there, for tools/find_rpf_key.py (the archives' AES key is in it).
    bv = sdk / "src" / "codegen" / "binary_view.cpp"
    edit(bv,
         "  return view;\n}\n",
         "  if (const char* dump = std::getenv(\"REX_DUMP_IMAGE\")) {\n"
         "    if (std::FILE* f = std::fopen(dump, \"wb\")) {\n"
         "      for (const auto& s : view.sections_) {\n"
         "        if (!s.data || s.baseAddress < view.baseAddress_) continue;\n"
         "        std::fseek(f, long(s.baseAddress - view.baseAddress_), SEEK_SET);\n"
         "        std::fwrite(s.data, 1, s.size, f);\n"
         "      }\n"
         "      std::fclose(f);\n"
         "    }\n"
         "  }\n"
         "  return view;\n}\n")
    edit(bv, "#include <limits>\n", "#include <cstdio>\n#include <cstdlib>\n#include <limits>\n")

    edit(sdk / "src" / "filesystem" / "devices" / "disc_image_device.cpp",
         "#include <rex/platform.h>\n#if REX_PLATFORM_PS5\n#include <rex/filesystem/direct_io.h>\n#endif\n",
         "#include <rex/platform.h>\n#include <rex/filesystem/direct_io.h>\n")

    # The bring-up counters (rex/ps5_diag.h) are counted outside PS5-only code
    # too; elsewhere than the PS5 nothing defines them (ps5_diag.cpp is PS5's).
    (sdk / "src" / "core" / "ps5_diag_host.cpp").write_text(
        "// [mgr] rex/ps5_diag.h's counters off the PS5 (ps5_diag.cpp is PS5-only).\n"
        "#include <rex/ps5_diag.h>\n\n"
        "namespace rex::ps5diag {\n"
        "std::atomic<uint64_t> counters[kCount];\n"
        "uintptr_t guest_arena_lo = 0, guest_arena_hi = 0;\n"
        "}  // namespace rex::ps5diag\n")
    edit(sdk / "src" / "core" / "CMakeLists.txt",
         "    target_sources(rexcore PRIVATE ps5_libc_extras.c ps5_diag.cpp)\n",
         "    target_sources(rexcore PRIVATE ps5_libc_extras.c ps5_diag.cpp)\n"
         "else()\n"
         "    target_sources(rexcore PRIVATE ps5_diag_host.cpp)  # [mgr]\n"
         "endif()\n"
         "if(PS5)\n")

    # PS5 audio: a sample the game's mixer left NaN / infinite (std::clamp lets
    # NaN through, and its int16 cast is garbage: loud crackle) is played as 0,
    # and every 10 s with any, the count and the loudest sample are logged.
    drv = sdk / "src" / "audio" / "ps5" / "ps5_audio_driver.cpp"
    edit(drv,
         "  bool started = false, in_gap = false;\n  uint32_t gaps = 0, silent = 0, played = 0;\n",
         "  bool started = false, in_gap = false;\n  uint32_t gaps = 0, silent = 0, played = 0;\n"
         "  uint32_t bad = 0, clipped = 0;  // [mgr]\n  float peak = 0.0f;\n")
    edit(drv,
         "      gaps = silent = played = 0;\n",
         "      if (bad || clipped) {\n"
         "        REXAPU_INFO(\"PS5 audio: {} NaN/inf samples (played as 0), {} clipped, peak {:.2f} in 10 s\", bad,\n"
         "                    clipped, peak);\n"
         "      }\n"
         "      bad = clipped = 0, peak = 0.0f;\n"
         "      gaps = silent = played = 0;\n")
    edit(drv,
         "        float s = std::clamp(stereo[i], -1.0f, 1.0f);\n",
         "        float s = stereo[i];\n"
         "        if (!std::isfinite(s)) s = 0.0f, ++bad;\n"
         "        peak = std::max(peak, std::fabs(s));\n"
         "        if (std::fabs(s) > 1.0f) ++clipped;\n"
         "        s = std::clamp(s, -1.0f, 1.0f);\n")
    edit(drv, "#include <algorithm>\n", "#include <algorithm>\n#include <cmath>\n")

    # Audio diagnostics: what the XMA decoder did (contexts decoded, decode
    # errors, output buffers full, input run dry) every 10 s, and the PS5
    # output's first 90 s of sound in logs/mgr_audio.raw (48 kHz s16 stereo;
    # only with logs/capture.txt)
    # with a count of frames identical to the one before (a stuck voice
    # buzzes) -- the noise, to look at instead of guessing.
    xc = sdk / "src" / "audio" / "xma_context.cpp"
    edit(xc,
         "namespace rex::audio {\n\nusing stream::BitStream;\n",
         "namespace rex::audio {\n\n"
         "// [mgr] decoded, errors, output full, input dry, kicks of a disabled context\n"
         "std::atomic<uint64_t> mgr_xma_stats[5];\n"
         "static void MgrXmaReport() {\n"
         "  static std::atomic<int64_t> last{0};\n"
         "  const int64_t now = std::chrono::duration_cast<std::chrono::seconds>(\n"
         "      std::chrono::steady_clock::now().time_since_epoch()).count();\n"
         "  int64_t prev = last.load();\n"
         "  if (now - prev < 10 || !last.compare_exchange_strong(prev, now)) return;\n"
         "  REXAPU_INFO(\"XMA 10 s: {} decodes, {} errors, {} output full, {} input dry\",\n"
         "              mgr_xma_stats[0].exchange(0), mgr_xma_stats[1].exchange(0),\n"
         "              mgr_xma_stats[2].exchange(0), mgr_xma_stats[3].exchange(0));\n"
         "}\n\n"
         "using stream::BitStream;\n")
    edit(xc, "#include <algorithm>\n#include <cstring>\n",
         "#include <algorithm>\n#include <atomic>\n#include <chrono>\n#include <cstring>\n")
    edit(xc,
         "  if (minimum_subframe_decode_count > remaining_subframe_blocks_in_output_buffer_) {\n",
         "  MgrXmaReport();\n"
         "  if (minimum_subframe_decode_count > remaining_subframe_blocks_in_output_buffer_) {\n"
         "    ++mgr_xma_stats[2];\n")
    edit(xc,
         "    Decode(&data);\n    Consume(&output_rb, &data);\n",
         "    Decode(&data);\n    Consume(&output_rb, &data);\n    ++mgr_xma_stats[0];\n")
    edit(xc,
         "    if (!data.IsAnyInputBufferValid() || data.error_status == 4) {\n      break;\n",
         "    if (!data.IsAnyInputBufferValid() || data.error_status == 4) {\n"
         "      ++mgr_xma_stats[data.error_status == 4 ? 1 : 3];\n      break;\n")

    drv = sdk / "src" / "audio" / "ps5" / "ps5_audio_driver.cpp"
    edit(drv,
         "  uint32_t bad = 0, clipped = 0;  // [mgr]\n",
         "  uint32_t bad = 0, clipped = 0, repeats = 0;  // [mgr]\n"
         "  std::vector<int16_t> previous(kChannelSamples * 2, 0);\n"
         "  FILE* capture = nullptr;\n  uint64_t captured = 0;  // (frames)\n")
    edit(drv,
         "      if (bad || clipped) {\n",
         "      REXAPU_INFO(\"PS5 audio 10 s: {} frames repeated exactly, peak {:.2f}\", repeats, peak);\n"
         "      repeats = 0;\n"
         "      if (bad || clipped) {\n")
    edit(drv,
         "    sceAudioOutOutput(port_, pcm);\n  }\n",
         "    if (frame) {\n"
         "      bool nonzero = false;\n"
         "      for (uint32_t i = 0; i < kChannelSamples * 2 && !nonzero; ++i) nonzero = pcm[i] != 0;\n"
         "      if (nonzero && std::memcmp(previous.data(), pcm, sizeof(pcm)) == 0) ++repeats;\n"
         "      std::memcpy(previous.data(), pcm, sizeof(pcm));\n"
         "      // (only with logs/capture.txt, as the frame captures)\n"
         "      static const bool capture_wanted = [] {\n"
         "        std::FILE* f = std::fopen(\"/app0/logs/capture.txt\", \"rb\");\n"
         "        if (f) std::fclose(f);\n"
         "        return f != nullptr;\n"
         "      }();\n"
         "      if (!capture && !captured && !capture_wanted) captured = 1;\n"
         "      if (!capture && !captured) {\n"
         "        capture = std::fopen(\"/app0/logs/mgr_audio.raw\", \"wb\");\n"
         "        if (!capture) captured = 1;\n"
         "      }\n"
         "      if (capture) {\n"
         "        std::fwrite(pcm, sizeof(pcm), 1, capture);\n"
         "        if (++captured >= uint64_t(kFrequency) * 90 / kChannelSamples) {\n"
         "          std::fclose(capture);\n          capture = nullptr;\n"
         "          REXAPU_INFO(\"PS5 audio: 90 s captured to logs/mgr_audio.raw\");\n"
         "        }\n"
         "      }\n"
         "    }\n"
         "    sceAudioOutOutput(port_, pcm);\n  }\n"
         "  if (capture) std::fclose(capture);\n")
    edit(drv, "#include <cmath>\n", "#include <cmath>\n#include <cstdio>\n#include <vector>\n")

    # XMA decoder: where the framework's decoder differs from Xenia canary's
    # (xma_context_new.cc), each feeding the codec a wrong frame. Gameplay had
    # 30-50% of decode passes end in error_status 4 and the capture a 62.5 Hz
    # buzz (one 512-sample frame at 32 kHz):
    # - a packet that only continues an earlier frame was skipped by moving to
    #   the next packet in memory, which in an interleaved (multi-stream:
    #   cutscene and gameplay surround) buffer belongs to another stream;
    #   Xenia follows the packet's own skip count.
    # - a packet past the end of the current buffer was always taken as the
    #   next buffer's first packet; it is (index - count) of the next buffer.
    # - the search for the next frame stopped at the end of the current
    #   buffer instead of going on into the next one.
    # - Work set error_status 4 when one pass made no progress (waiting for
    #   the game's next buffer is not an error) and dropped the rest of a
    #   decoded frame on an error; Xenia stops without an error and drains
    #   the frame first.
    # Plus a count per error site, logged with the 10 s report.
    edit(xc,
         "std::atomic<uint64_t> mgr_xma_stats[5];\n",
         "std::atomic<uint64_t> mgr_xma_stats[5];\n"
         "std::atomic<uint64_t> mgr_xma_err[16];  // per error_status = 4 site in Decode\n"
         "std::atomic<uint64_t> mgr_xma_stale;  // kicks that began with error_status 4\n")
    edit(xc,
         "              mgr_xma_stats[2].exchange(0), mgr_xma_stats[3].exchange(0));\n",
         "              mgr_xma_stats[2].exchange(0), mgr_xma_stats[3].exchange(0));\n"
         "  std::string sites;\n"
         "  for (auto& e : mgr_xma_err) sites += std::to_string(e.exchange(0)) + \" \";\n"
         "  REXAPU_INFO(\"XMA errors by site: {}| begun in error {}, stalled {}\", sites,\n"
         "              mgr_xma_stale.exchange(0), mgr_xma_stats[4].exchange(0));\n")
    edit(xc, "#include <chrono>\n#include <cstring>\n",
         "#include <chrono>\n#include <cstring>\n#include <string>\n")
    edit(xc,
         "  memory::RingBuffer output_rb = PrepareOutputRingBuffer(&data);\n",
         "  memory::RingBuffer output_rb = PrepareOutputRingBuffer(&data);\n"
         "  if (data.error_status == 4) ++mgr_xma_stale;\n")
    edit(xc,
         "    // Invalid packets must not leave the decoder worker spinning forever.\n"
         "    if (data.IsAnyInputBufferValid() && data.error_status != 4 &&\n"
         "        data.input_buffer_read_offset == old_offset && data.current_buffer == old_buffer &&\n"
         "        data.IsAnyInputBufferValid() == old_valid &&\n"
         "        current_frame_remaining_subframes_ == old_remaining &&\n"
         "        remaining_subframe_blocks_in_output_buffer_ == old_capacity) {\n"
         "      data.error_status = 4;\n"
         "      handoff::Record(\"xma-error\", id_, {old_offset, old_buffer}, \"decode-no-progress\");\n"
         "    }\n"
         "    if (!data.IsAnyInputBufferValid() || data.error_status == 4) {\n"
         "      ++mgr_xma_stats[data.error_status == 4 ? 1 : 3];\n      break;\n    }\n",
         "    // [mgr] As Xenia: finish delivering a decoded frame before stopping\n"
         "    // on an error or on running out of input, and stop without an error\n"
         "    // when a pass made no progress (waiting for the game's next buffer).\n"
         "    if ((!data.IsAnyInputBufferValid() || data.error_status == 4) &&\n"
         "        current_frame_remaining_subframes_ == 0) {\n"
         "      ++mgr_xma_stats[data.error_status == 4 ? 1 : 3];\n      break;\n    }\n"
         "    if (data.input_buffer_read_offset == old_offset && data.current_buffer == old_buffer &&\n"
         "        data.IsAnyInputBufferValid() == old_valid &&\n"
         "        current_frame_remaining_subframes_ == old_remaining &&\n"
         "        remaining_subframe_blocks_in_output_buffer_ == old_capacity) {\n"
         "      ++mgr_xma_stats[4];\n      break;\n    }\n")
    # The next buffer's packet (index - count), within that buffer's length.
    edit(xc,
         "  const uint8_t next_buffer_index = data->current_buffer ^ 1;\n"
         "  if (!data->IsInputBufferValid(next_buffer_index)) {\n"
         "    return nullptr;\n  }\n",
         "  const uint8_t next_buffer_index = data->current_buffer ^ 1;\n"
         "  if (!data->IsInputBufferValid(next_buffer_index)) {\n"
         "    return nullptr;\n  }\n"
         "  next_packet_index -= current_input_packet_count;  // [mgr]\n"
         "  if (next_packet_index >= data->GetInputBufferPacketCount(next_buffer_index)) {\n"
         "    return nullptr;\n  }\n")
    edit(xc,
         "  return memory()->TranslatePhysical(next_buffer_address);\n",
         "  return memory()->TranslatePhysical(next_buffer_address) + next_packet_index * kBytesPerPacket;\n")
    # A continuation-only packet: follow its skip count to this stream's next.
    edit(xc,
         "      return (next_packet_index * kBitsPerPacket) + packet_frame_offset;\n"
         "    }\n"
         "    next_packet_index++;\n",
         "      return (next_packet_index * kBitsPerPacket) + packet_frame_offset;\n"
         "    }\n"
         "    const uint8_t next_skip = xma::GetPacketSkipCount(next_packet);  // [mgr]\n"
         "    if (next_skip == 0xFF) {\n      break;\n    }\n"
         "    next_packet_index += next_skip + 1;\n")
    # [audit 2026-11-05] Found in Max Payne 3; the clone's rename put MGR's name on it. MGR runs with
    # readback_resolve "none" (mgr_app.cpp's start line; 295bdd2 dropped MP3's "fast"), so this block
    # and the 256 KB readback block below never run for MGR. They stay for a port that sets "fast".
    # readback_resolve "fast" (Max Payne 3's HDR adaptation reads the
    # luminance it resolved on the CPU, Xenia game-compatibility #42) hands
    # the game the previous resolve's buffer without checking that the GPU
    # has written it: the slot can still be queued, or be fresh memory never
    # written at all. The game's exposure then adapts to garbage (NaN sticks)
    # and gameplay goes dark. As the memexport readback beside it does:
    # remember the submission that wrote each slot, wait for it when it is in
    # flight, and when it is this very submission (a second resolve to the
    # same place this frame) fall back to a full sync of the current one.
    vcp = sdk / "src" / "graphics" / "vulkan" / "command_processor.cpp"
    # Occlusion queries: when the 8192 host queries wrapped, AcquireOcclusionQueryIndex waited
    # for every pending one (the GPU drained) - every few frames in scenes full of light flares,
    # up to a quarter of the GPU thread's time in the chapter 1 log. Only a pending query on the
    # index being reused has to be waited for: the queue is in allocation order, so that is its
    # front, and it is 8192 queries old (long done) in practice.
    edit(vcp,
         "  if (occlusion_query_cursor_ >= kMaxOcclusionQueries) {\n"
         "    // Results still in flight must not be overwritten by the reused indices.\n"
         "    CompleteOcclusionQueries(true);\n"
         "    occlusion_query_cursor_ = 0;\n"
         "  }\n"
         "  host_index_out = occlusion_query_cursor_++;\n",
         "  if (occlusion_query_cursor_ >= kMaxOcclusionQueries) {\n"
         "    occlusion_query_cursor_ = 0;\n"
         "  }\n"
         "  // [mgr] A result still in flight must not be overwritten by the reused index: only the\n"
         "  // oldest pending query can hold it (allocation order), so wait for that one alone.\n"
         "  while (!pending_occlusion_queries_.empty() &&\n"
         "         pending_occlusion_queries_.front().host_index == occlusion_query_cursor_ && !device_lost_) {\n"
         "    const uint64_t submission = pending_occlusion_queries_.front().submission;\n"
         "    if (submission_completed_ < submission) {\n"
         "      CheckSubmissionFenceAndDeviceLoss(submission);\n"
         "      if (submission_completed_ < submission) break;\n"
         "    }\n"
         "    CompleteOcclusionQueries(false);\n"
         "  }\n"
         "  host_index_out = occlusion_query_cursor_++;\n")
    edit(vcp,
         "  PushBufferMemoryBarrier(readback.buffers[write_index], 0, written_length,\n"
         "                          VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,\n"
         "                          VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT);\n",
         "  PushBufferMemoryBarrier(readback.buffers[write_index], 0, written_length,\n"
         "                          VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,\n"
         "                          VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT);\n"
         "  readback.submission_written[write_index] = GetCurrentSubmission();  // [mgr]\n"
         "  readback.written_size[write_index] = written_length;\n")
    edit(vcp,
         "  bool is_cache_miss = false;\n"
         "  if (use_delayed_sync && (readback.buffers[read_index] == VK_NULL_HANDLE ||\n"
         "                           written_length > readback.sizes[read_index] ||\n"
         "                           readback.mapped_data[read_index] == nullptr)) {\n",
         "  bool is_cache_miss = false;\n"
         "  // [mgr] The previous slot is usable once the GPU has written it; until\n"
         "  // then the guest keeps the older data (waiting here held the CPU to\n"
         "  // the GPU's previous frame, every frame).\n"
         "  if (use_delayed_sync && readback.buffers[read_index] != VK_NULL_HANDLE &&\n"
         "      readback.submission_written[read_index] &&\n"
         "      readback.submission_written[read_index] > submission_completed_ &&\n"
         "      written_length <= readback.written_size[read_index]) {\n"
         "    CheckSubmissionFenceAndDeviceLoss(0);\n"
         "    if (readback.submission_written[read_index] > submission_completed_) {\n"
         "      rex::mgr_perf::g_n[rex::mgr_perf::kReadbackLate].fetch_add(1, std::memory_order_relaxed);\n"
         "      // (the same slot takes the next copy too: the older one gets time)\n"
         "      return true;\n"
         "    }\n"
         "  }\n"
         "  if (use_delayed_sync && (readback.buffers[read_index] == VK_NULL_HANDLE ||\n"
         "                           written_length > readback.sizes[read_index] ||\n"
         "                           readback.mapped_data[read_index] == nullptr ||\n"
         "                           written_length > readback.written_size[read_index] ||\n"
         "                           !readback.submission_written[read_index] ||\n"
         "                           readback.submission_written[read_index] > submission_completed_)) {\n")

    # XMA loops: every gameplay decode error (site 2, 22k per 10 s) was the
    # framework's own "invalid loop interval" check, which Xenia doesn't
    # have. It rejects legal loop data (loop_subframe_end is a 3-bit field,
    # 4..7 meaning the whole frame) and stops every looping voice (ambience,
    # music, gunfire tails) at its loop end; the error then sticks ("begun
    # in error"). The loop code below copes with any values (the output
    # limit is clamped to the frame). The loop-start skip is applied as
    # Xenia does: only a skip shorter than the frame.
    edit(xc,
         "  if (is_loop_end_frame &&\n"
         "      (data->loop_subframe_end > 3 || data->loop_subframe_skip > 4 ||\n",
         "  if (false && is_loop_end_frame &&  // [mgr] as Xenia: no such check\n"
         "      (data->loop_subframe_end > 3 || data->loop_subframe_skip > 4 ||\n")
    edit(xc,
         "      current_frame_remaining_subframes_ -=\n"
         "          std::min<uint8_t>(skip, current_frame_remaining_subframes_);\n",
         "      if (skip < current_frame_remaining_subframes_) {  // [mgr] as Xenia\n"
         "        current_frame_remaining_subframes_ -= skip;\n      }\n")

    # Frame capture (with a logs/capture.txt file): at 90, 150, 210 and 300 s
    # after the first draw, one whole frame goes to logs/mgr_frame_<s>.bin:
    # every draw (render target, depth, blend registers, shaders, the pixel
    # shader's float constants, the texture fetch constants it samples),
    # every resolve (copy registers and the resolved bytes as the CPU sees
    # them) in order, and each shader's ucode once. tools/mgr_frame.py turns
    # it into images of every pass.
    edit(vcp, "#include <cstring>\n#include <iterator>\n",
         "#include <chrono>\n#include <cstdio>\n#include <cstring>\n#include <iterator>\n"
         "#include <unordered_set>\n")
    edit(vcp,
         "namespace rex::graphics::vulkan {\n\nnamespace {\n",
         "namespace rex::graphics::vulkan {\n\nnamespace {\n\n"
         "// [mgr] Frame capture (see ci/patch_framework.py).\n"
         "struct MgrCapture {\n"
         "  std::FILE* file = nullptr;\n"
         "  uint64_t frame = 0, armed_frame = 0;\n"
         "  uint32_t taken = 0, seq = 0;\n"
         "  std::chrono::steady_clock::time_point start{};\n"
         "  std::unordered_set<uint64_t> shaders;\n"
         "};\n"
         "MgrCapture mgr_cap;\n"
         "constexpr uint32_t kMgrCaptureSeconds[] = {90, 150, 210, 300};\n"
         "void MgrCapWrite(const void* p, size_t n) {\n"
         "  if (mgr_cap.file) std::fwrite(p, 1, n, mgr_cap.file);\n"
         "}\n"
         "template <typename T>\n"
         "void MgrCapPut(const T& v) {\n  MgrCapWrite(&v, sizeof(v));\n}\n"
         "bool MgrCapActive(uint64_t frame) {\n"
         "  // (only with logs/capture.txt: a capture holds its frame up). Asked first: this runs for\n"
         "  // every draw, and the clock read below was a tenth of the GPU thread's time\n"
         "  static const bool enabled = [] {\n"
         "    std::FILE* f = std::fopen(\"/app0/logs/capture.txt\", \"rb\");\n"
         "    if (f) std::fclose(f);\n"
         "    return f != nullptr;\n"
         "  }();\n"
         "  if (!enabled) return false;\n"
         "  const auto now = std::chrono::steady_clock::now();\n"
         "  if (mgr_cap.start == std::chrono::steady_clock::time_point{}) mgr_cap.start = now;\n"
         "  if (mgr_cap.file && frame != mgr_cap.frame) {\n"
         "    std::fclose(mgr_cap.file);\n    mgr_cap.file = nullptr;\n"
         "    REXGPU_INFO(\"mgr capture: frame {} written ({} records)\", mgr_cap.frame, mgr_cap.seq);\n"
         "  }\n"
         "  if (!mgr_cap.file && enabled && mgr_cap.taken < std::size(kMgrCaptureSeconds)) {\n"
         "    const auto seconds =\n"
         "        std::chrono::duration_cast<std::chrono::seconds>(now - mgr_cap.start).count();\n"
         "    if (!mgr_cap.armed_frame && seconds >= kMgrCaptureSeconds[mgr_cap.taken]) {\n"
         "      mgr_cap.armed_frame = frame + 1;\n"
         "    }\n"
         "    if (mgr_cap.armed_frame && frame >= mgr_cap.armed_frame) {\n"
         "      char path[64];\n"
         "      std::snprintf(path, sizeof(path), \"/app0/logs/mgr_frame_%u.bin\",\n"
         "                    unsigned(kMgrCaptureSeconds[mgr_cap.taken]));\n"
         "      mgr_cap.file = std::fopen(path, \"wb\");\n"
         "      mgr_cap.frame = frame;\n      mgr_cap.armed_frame = 0;\n      mgr_cap.seq = 0;\n"
         "      ++mgr_cap.taken;\n      mgr_cap.shaders.clear();\n"
         "      if (mgr_cap.file) {\n"
         "        MgrCapWrite(\"MGRF\", 4);\n        MgrCapPut(uint32_t(1));\n        MgrCapPut(frame);\n"
         "      }\n"
         "    }\n"
         "  }\n"
         "  return mgr_cap.file != nullptr;\n"
         "}\n"
         "void MgrCapShader(const Shader* shader) {\n"
         "  if (!shader || !mgr_cap.shaders.insert(shader->ucode_data_hash()).second) return;\n"
         "  MgrCapWrite(\"S\", 1);\n"
         "  MgrCapPut(shader->ucode_data_hash());\n"
         "  MgrCapPut(uint32_t(shader->type()));\n"
         "  MgrCapPut(uint32_t(shader->ucode_dword_count()));\n"
         "  MgrCapWrite(shader->ucode_dwords(), shader->ucode_dword_count() * 4);\n"
         "}\n"
         "void MgrCapRegs(const RegisterFile& regs) {\n"
         "  static const uint32_t kRegs[] = {\n"
         "      XE_GPU_REG_RB_SURFACE_INFO,  XE_GPU_REG_RB_COLOR_INFO,     XE_GPU_REG_RB_COLOR1_INFO,\n"
         "      XE_GPU_REG_RB_COLOR2_INFO,   XE_GPU_REG_RB_COLOR3_INFO,    XE_GPU_REG_RB_DEPTH_INFO,\n"
         "      XE_GPU_REG_RB_COLOR_MASK,    XE_GPU_REG_RB_DEPTHCONTROL,   XE_GPU_REG_RB_MODECONTROL,\n"
         "      XE_GPU_REG_RB_BLENDCONTROL0, XE_GPU_REG_RB_COPY_CONTROL,   XE_GPU_REG_RB_COPY_DEST_INFO,\n"
         "      XE_GPU_REG_RB_COPY_DEST_PITCH, XE_GPU_REG_RB_COPY_DEST_BASE};\n"
         "  for (uint32_t r : kRegs) MgrCapPut(regs[r]);\n"
         "}\n")
    edit(vcp,
         "  bool memexport_writes_possible = memexport_used_vertex || memexport_used_pixel;\n",
         "  bool memexport_writes_possible = memexport_used_vertex || memexport_used_pixel;\n"
         "  if (MgrCapActive(frame_current_)) {  // [mgr] frame capture: the draw\n"
         "    MgrCapShader(vertex_shader);\n    MgrCapShader(pixel_shader);\n"
         "    MgrCapWrite(\"D\", 1);\n    MgrCapPut(mgr_cap.seq++);\n"
         "    MgrCapRegs(regs);\n"
         "    MgrCapPut(uint32_t(prim_type));\n    MgrCapPut(index_count);\n"
         "    MgrCapPut(vertex_shader->ucode_data_hash());\n"
         "    MgrCapPut(pixel_shader ? pixel_shader->ucode_data_hash() : uint64_t(0));\n"
         "    MgrCapWrite(&regs.values[XE_GPU_REG_SHADER_CONSTANT_000_X + 256 * 4], 256 * 16);\n"
         "    const auto* bindings = pixel_shader ? &pixel_shader->texture_bindings() : nullptr;\n"
         "    MgrCapPut(uint32_t(bindings ? bindings->size() : 0));\n"
         "    if (bindings) {\n"
         "      for (const auto& binding : *bindings) {\n"
         "        MgrCapPut(binding.fetch_constant);\n"
         "        MgrCapWrite(&regs.values[XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0 + 6 * binding.fetch_constant],\n"
         "                    6 * 4);\n"
         "      }\n"
         "    }\n"
         "  }\n")
    edit(vcp,
         "    resolve_succeeded = IssueCopy_ReadbackResolvePath();\n  }\n",
         "    resolve_succeeded = IssueCopy_ReadbackResolvePath();\n  }\n"
         "  if (MgrCapActive(frame_current_)) {  // [mgr] frame capture: the resolve\n"
         "    MgrCapWrite(\"C\", 1);\n    MgrCapPut(mgr_cap.seq++);\n"
         "    MgrCapRegs(*register_file_);\n"
         "    MgrCapPut(uint32_t(resolve_succeeded));\n"
         "    MgrCapPut(frame_flow_resolve_address_);\n"
         "    const uint8_t* resolved = frame_flow_resolve_length_ <= (16u << 20)\n"
         "        ? memory_->TranslatePhysical(frame_flow_resolve_address_) : nullptr;\n"
         "    MgrCapPut(uint32_t(resolved ? frame_flow_resolve_length_ : 0));\n"
         "    if (resolved) MgrCapWrite(resolved, frame_flow_resolve_length_);\n"
         "  }\n")

    # A draw whose depth test can never pass and that has stencil off writes
    # nothing (no color, depth or stencil): skip it before it binds render
    # targets. Max Payne 3 (where it was found; the clone's rename said MGR) issues one (depth only, zfunc NEVER) on its depth
    # buffer reinterpreted as 640-wide 2x MSAA between the G-buffer and the
    # stencil-tested deferred lighting; on host render targets binding it
    # converts the depth/stencil away and back (lossy) for nothing.
    edit(vcp,
         "  if (surface_pitch_is_zero && is_rasterization_done) {\n",
         "  if (is_rasterization_done && !memexport_used_vertex) {  // [mgr]\n"
         "    const auto depth_control = draw_util::GetNormalizedDepthControl(regs);\n"
         "    if (depth_control.z_enable && !depth_control.stencil_enable &&\n"
         "        depth_control.zfunc == xenos::CompareFunction::kNever) {\n"
         "      ++frame_flow_no_effect_draws_;\n      return true;\n    }\n"
         "  }\n"
         "  if (surface_pitch_is_zero && is_rasterization_done) {\n")
    vrt = sdk / "src" / "graphics" / "vulkan" / "render_target_cache.cpp"
    edit(vrt,
         "  if (GetPath() == Path::kPixelShaderInterlock) {\n"
         "    // The first operation will likely be drawing.\n",
         "  REXGPU_INFO(\"VulkanRenderTargetCache: {} path (fragment shader interlock {})\",  // [mgr]\n"
         "              path_ == Path::kPixelShaderInterlock ? \"fragment shader interlock (EDRAM)\"\n"
         "                                                   : \"host render targets\",\n"
         "              fsi_path_supported ? \"supported\" : \"unsupported\");\n"
         "  if (GetPath() == Path::kPixelShaderInterlock) {\n"
         "    // The first operation will likely be drawing.\n")

    # Integer number format (Xenia canary packs and fetches it, this
    # framework's resolve shaders and texture fetch only know fractions).
    # Max Payne 3 (where it was found; the clone's rename said MGR) resolves its HDR scene (7e3) to k_16_16_16_16 with number
    # format "unsigned integer" and exponent bias +11 (a 16-bit integer with 11
    # fractional bits) and samples it with num_format integer and exp_adjust
    # -13. Packed as a 0..1 fraction every lit pixel saturated (all white);
    # fetched as a fraction it would read 65535 times too dark.
    # - resolve: for 16-bit components, 2^(bias - 16) through the fraction
    #   packer writes the same integers as 2^bias through an integer packer
    #   (to 1/65536).
    # - fetch: an integer-format 16-bit texture gets exp_adjust + 16 in the
    #   fetch constants the shaders read, the fraction times 65535 (to 1/65536).
    drw = sdk / "src" / "graphics" / "util" / "draw.cpp"
    edit(drw,
         "  // Handle k_16_16 and k_16_16_16_16 range.\n"
         "  info_out.copy_dest_info.copy_dest_exp_bias = exp_bias;\n",
         "  // [mgr] Unsigned integer destinations through the fraction packer.\n"
         "  if (!is_depth && rb_copy_dest_info.copy_dest_number ==\n"
         "                       xenos::SurfaceNumberFormat::kUnsignedInteger) {\n"
         "    switch (xenos::ColorFormat(dest_format)) {\n"
         "      case xenos::ColorFormat::k_16:\n"
         "      case xenos::ColorFormat::k_16_16:\n"
         "      case xenos::ColorFormat::k_16_16_16_16:\n"
         "        exp_bias = std::max(exp_bias - int32_t(16), int32_t(-32));\n"
         "        break;\n"
         "      default:\n"
         "        break;\n"
         "    }\n"
         "  }\n"
         "  // Handle k_16_16 and k_16_16_16_16 range.\n"
         "  info_out.copy_dest_info.copy_dest_exp_bias = exp_bias;\n")
    edit(vcp,
         "      std::memcpy(mapping, &regs[XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0], kFetchConstantsSize);\n",
         "      std::memcpy(mapping, &regs[XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0], kFetchConstantsSize);\n"
         "      // [mgr] Integer-format 16-bit textures: fraction * 65535 (see\n"
         "      // ci/patch_framework.py).\n"
         "      for (uint32_t i = 0; i < 32; ++i) {\n"
         "        uint32_t* fetch = reinterpret_cast<uint32_t*>(mapping) + 6 * i;\n"
         "        const uint32_t type = fetch[0] & 3, format = fetch[1] & 0x3F;\n"
         "        if ((type != 2 && type != 0) || !(fetch[3] & 1) ||\n"
         "            (format != 24 && format != 25 && format != 26)) {\n"
         "          continue;\n"
         "        }\n"
         "        const int32_t exp_adjust =\n"
         "            std::min((int32_t(fetch[3] << 13) >> 26) + 16, int32_t(31));\n"
         "        fetch[3] = (fetch[3] & ~(UINT32_C(0x3F) << 13)) | ((uint32_t(exp_adjust) & 0x3F) << 13);\n"
         "      }\n")

    # Readback only what the CPU reads: "fast" copied every resolve of every
    # frame back (55 a frame, ~40 MB with the 7.5 MB HDR copies) and memcpy'd
    # it into guest memory on the GPU thread. The game's CPU reads are its
    # luminance / exposure resolves (a few KB); the GPU never needs these
    # copies. Up to 256 KB, as Xenia's purpose for it (HDR adaptation).
    edit(vcp,
         "  if (!memory_->TranslatePhysical(written_address)) {\n    return true;\n  }\n",
         "  if (!memory_->TranslatePhysical(written_address)) {\n    return true;\n  }\n"
         "  if (written_length > (256u << 10) && !mgr_cap.file) {  // [mgr] only what the CPU reads\n"
         "    return true;\n  }\n")
    edit(vcp,
         "  uint32_t read_index = write_index;\n  if (use_delayed_sync) {\n",
         "  if (mgr_cap.file) use_delayed_sync = false;  // [mgr] captured frames: current data\n"
         "  uint32_t read_index = write_index;\n  if (use_delayed_sync) {\n")

    # Texture fetch result exponent bias (exp_adjust) from the fetch constant
    # word 3, bits 13:18 (xenos.h, and the DXBC translator). The SPIR-V
    # translator took bits 13:18 of word 4 - part of the LOD bias - so on
    # Vulkan no texture got its exp_adjust, and textures with a LOD bias got a
    # random scale. Max Payne 3 (where it was found; the clone's rename said MGR) reads its HDR scene, bloom and luminance with
    # exp_adjust -13 (+16 above for the integer format): every post-processing
    # pass saw the scene 8 times too dark (the dark, grey gameplay).
    sft = sdk / "src" / "graphics" / "pipeline" / "shader" / "spirv_translator_fetch.cpp"
    edit(sft,
         "        spv::Id result_exponent_bias = builder_->createBinBuiltinCall(\n"
         "            type_float_, ext_inst_glsl_std_450_, GLSLstd450Ldexp, const_float_1_,\n"
         "            builder_->createTriOp(spv::OpBitFieldSExtract, type_int_, fetch_constant_word_4_signed,\n"
         "                                  builder_->makeUintConstant(13), builder_->makeUintConstant(6)));\n",
         "        // [mgr] Word 3 (see ci/patch_framework.py), not word 4.\n"
         "        id_vector_temp_.clear();\n"
         "        id_vector_temp_.push_back(const_int_0_);\n"
         "        id_vector_temp_.push_back(\n"
         "            builder_->makeIntConstant(int((fetch_constant_word_0_index + 3) >> 2)));\n"
         "        id_vector_temp_.push_back(\n"
         "            builder_->makeIntConstant(int((fetch_constant_word_0_index + 3) & 3)));\n"
         "        spv::Id fetch_constant_word_3_signed = builder_->createUnaryOp(\n"
         "            spv::OpBitcast, type_int_,\n"
         "            builder_->createLoad(builder_->createAccessChain(spv::StorageClassUniform,\n"
         "                                                             uniform_fetch_constants_,\n"
         "                                                             id_vector_temp_),\n"
         "                                 spv::NoPrecision));\n"
         "        spv::Id result_exponent_bias = builder_->createBinBuiltinCall(\n"
         "            type_float_, ext_inst_glsl_std_450_, GLSLstd450Ldexp, const_float_1_,\n"
         "            builder_->createTriOp(spv::OpBitFieldSExtract, type_int_, fetch_constant_word_3_signed,\n"
         "                                  builder_->makeUintConstant(13), builder_->makeUintConstant(6)));\n")

    # Occlusion queries on the ACCURATE renderer (fragment shader interlock): the pixel shader does
    # the depth / stencil test itself and only skips its EDRAM writes for failing samples, so the
    # pixel stays alive and the host occlusion query counted every pixel drawn. The game's light
    # flares test their visibility with queries: every flare showed through walls. Kill the pixel
    # at the end of the shader (after its EDRAM writes) when no sample passed, as the console's
    # depth test would: the query then counts only the samples that passed.
    rb = sdk / "src" / "graphics" / "pipeline" / "shader" / "spirv_translator_rb.cpp"
    edit(rb,
         "void SpirvShaderTranslator::CompleteFragmentShaderInMain() {\n"
         "  // Loaded if needed.\n"
         "  spv::Id msaa_samples = spv::NoResult;\n",
         "void SpirvShaderTranslator::CompleteFragmentShaderInMain() {\n"
         "  // Loaded if needed.\n"
         "  spv::Id msaa_samples = spv::NoResult;\n"
         "\n"
         "  // [mgr] Whether any sample passed the FSI depth / stencil test (occlusion queries).\n"
         "  spv::Id var_fsi_any_sample_passed = spv::NoResult;\n"
         "  if (edram_fragment_shader_interlock_) {\n"
         "    var_fsi_any_sample_passed = builder_->createVariable(\n"
         "        spv::NoPrecision, spv::StorageClassFunction, type_bool_,\n"
         "        \"xe_var_fsi_any_sample_passed\", builder_->makeBoolConstant(false));\n"
         "  }\n")
    fsi_store_passed = (
        "      builder_->createStore(\n"
        "          builder_->createBinOp(\n"
        "              spv::OpINotEqual, type_bool_,\n"
        "              builder_->createBinOp(spv::OpBitwiseAnd, type_uint_, main_fsi_sample_mask_,\n"
        "                                    builder_->makeUintConstant((uint32_t(1) << 4) - 1)),\n"
        "              const_uint_0_),\n"
        "          var_fsi_any_sample_passed);  // [mgr]\n")
    edit(rb,
         "    if (FSI_IsDepthStencilEarly()) {\n"
         "      // Perform late depth / stencil writes for samples not discarded.\n",
         "    if (FSI_IsDepthStencilEarly()) {\n" + fsi_store_passed +
         "      // Perform late depth / stencil writes for samples not discarded.\n")
    edit(rb,
         "      FSI_DepthStencilTest(msaa_samples,\n"
         "                           fsi_pixel_potentially_killed || (color_targets_written & 0b1));\n",
         "      FSI_DepthStencilTest(msaa_samples,\n"
         "                           fsi_pixel_potentially_killed || (color_targets_written & 0b1));\n"
         + fsi_store_passed)
    edit(rb,
         "    builder_->createNoResultOp(spv::OpEndInvocationInterlockEXT);\n"
         "  }\n"
         "}\n",
         "    builder_->createNoResultOp(spv::OpEndInvocationInterlockEXT);\n"
         "\n"
         "    // [mgr] Not counted by occlusion queries when every sample failed (see ci/patch_framework.py).\n"
         "    SpirvBuilder::IfBuilder fsi_no_sample_passed_if(\n"
         "        builder_->createUnaryOp(\n"
         "            spv::OpLogicalNot, type_bool_,\n"
         "            builder_->createLoad(var_fsi_any_sample_passed, spv::NoPrecision)),\n"
         "        spv::SelectionControlDontFlattenMask, *builder_);\n"
         "    builder_->createNoResultOp(spv::OpKill);\n"
         "    // OpKill terminates the block.\n"
         "    fsi_no_sample_passed_if.makeEndIf(false);\n"
         "  }\n"
         "}\n")

    # Where the GPU thread's time goes (include/rex/mgr_perf.h, from
    # fw-files): timers around the stalls and the big steps, printed per frame
    # every 10 s as "mgr perf". The framework's "ps5 timing" line only counts
    # the GTA IV renderer's frames (all zeros here).
    def include_perf(path):
        text = path.read_text()
        if "#include <rex/mgr_perf.h>" in text:
            return
        i = text.index("\n#include ") + 1
        path.write_text(text[:i] + "#include <rex/mgr_perf.h>\n" + text[i:])
    cpb = sdk / "src" / "graphics" / "command_processor.cpp"
    vtc = sdk / "src" / "graphics" / "vulkan" / "texture_cache.cpp"
    vpc = sdk / "src" / "graphics" / "vulkan" / "pipeline_cache.cpp"
    for f in (cpb, vcp, vtc):
        include_perf(f)
    edit(vcp, "#include <rex/mgr_perf.h>\n",
         "#include <rex/mgr_perf.h>\n#include <rex/ps5_diag.h>\n#include <rex/frame_stats.h>\n"
         "#if defined(__PROSPERO__)\n#include <pthread.h>\n#endif\n")
    edit(cpb,
         "      PrepareForWait();\n      bool poll_background_work = PollBackgroundWork();\n",
         "      rex::mgr_perf::Scope mgr_perf_idle(rex::mgr_perf::kIdle);\n"
         "      PrepareForWait();\n      bool poll_background_work = PollBackgroundWork();\n")
    edit(cpb,
         "      if (wait >= 0x100) {\n        PrepareForWait();\n",
         "      if (wait >= 0x100) {\n"
         "        rex::mgr_perf::Scope mgr_perf_wait(rex::mgr_perf::kWaitRegMem);\n"
         "        PrepareForWait();\n")
    edit(vcp,
         "    VkResult wait_result =\n        vulkan_device->WaitForFences(",
         "    rex::mgr_perf::Scope mgr_perf_fence(rex::mgr_perf::kFenceWait);\n"
         "    VkResult wait_result =\n        vulkan_device->WaitForFences(")
    edit(vcp,
         "bool VulkanCommandProcessor::EndSubmission(bool is_swap) {\n",
         "bool VulkanCommandProcessor::EndSubmission(bool is_swap) {\n"
         "  rex::mgr_perf::Scope mgr_perf_submit(rex::mgr_perf::kSubmit);\n")
    edit(vcp,
         "                                       bool major_mode_explicit) {\n",
         "                                       bool major_mode_explicit) {\n"
         "  rex::mgr_perf::g_n[rex::mgr_perf::kDraw].fetch_add(1, std::memory_order_relaxed);\n")
    edit(vcp,
         "bool VulkanCommandProcessor::IssueCopy() {\n",
         "bool VulkanCommandProcessor::IssueCopy() {\n"
         "  rex::mgr_perf::Scope mgr_perf_copy(rex::mgr_perf::kCopy);\n")
    edit(vtc,
         "bool VulkanTextureCache::LoadTextureDataFromResidentMemoryImpl(Texture& texture, bool load_base,\n"
         "                                                               bool load_mips) {\n",
         "bool VulkanTextureCache::LoadTextureDataFromResidentMemoryImpl(Texture& texture, bool load_base,\n"
         "                                                               bool load_mips) {\n"
         "  rex::mgr_perf::Scope mgr_perf_texture(rex::mgr_perf::kTextureLoad);\n")
    edit(vcp,
         "bool VulkanCommandProcessor::EndGuestOcclusionQuery(uint32_t sample_count_address) {\n",
         "bool VulkanCommandProcessor::EndGuestOcclusionQuery(uint32_t sample_count_address) {\n"
         "  rex::mgr_perf::Scope mgr_perf_occlusion(rex::mgr_perf::kOcclusion);\n")
    edit(vcp,
         "                                       uint32_t frontbuffer_height) {\n  SCOPE_profile_cpu_f(\"gpu\");\n",
         "                                       uint32_t frontbuffer_height) {\n  SCOPE_profile_cpu_f(\"gpu\");\n"
         "  {\n"
         "    // [mgr] the GPU thread's time per frame, every 10 s (rex/mgr_perf.h)\n"
         "    using namespace rex::mgr_perf;\n"
         "    static uint64_t last_us = 0, frames = 0, prev_ns[kCount], prev_n[kCount];\n"
         "    const uint64_t now = NowUs();\n"
         "    {\n"
         "      // [mgr] a frame over 100 ms: when, and where the GPU thread's time went in it\n"
         "      static uint64_t swap_us = 0, swap_ns[kCount];\n"
         "      uint64_t cur[kCount];\n"
         "      for (uint32_t c = 0; c < kCount; ++c) cur[c] = g_ns[c].load(std::memory_order_relaxed);\n"
         "      if (swap_us && now - swap_us > 100000) {\n"
         "        auto d = [&](Counter c) { return double(cur[c] - swap_ns[c]) / 1e6; };\n"
         "        REXGPU_INFO(\"mgr frame hitch: {:.0f} ms; GPU thread: idle (waiting for the game) {:.0f}, wait_reg_mem {:.0f}, \"\n"
         "                    \"fences {:.0f}, submit {:.0f}, draws {:.0f} (pipelines {:.0f}, texture loads {:.0f}), copies {:.0f}, \"\n"
         "                    \"occlusion {:.0f}\",\n"
         "                    double(now - swap_us) / 1000.0, d(kIdle), d(kWaitRegMem), d(kFenceWait), d(kSubmit), d(kDraw),\n"
         "                    d(kPipeline), d(kTextureLoad), d(kCopy), d(kOcclusion));\n"
         "      }\n"
         "      swap_us = now;\n"
         "      for (uint32_t c = 0; c < kCount; ++c) swap_ns[c] = cur[c];\n"
         "    }\n"
         "    ++frames;\n"
         "    if (!last_us) {\n"
         "      last_us = now;\n"
         "      frames = 0;\n"
         "    } else if (now - last_us >= 10000000) {\n"
         "      double ms[kCount], n[kCount];\n"
         "      for (uint32_t c = 0; c < kCount; ++c) {\n"
         "        const uint64_t ns = g_ns[c].load(std::memory_order_relaxed), cn = g_n[c].load(std::memory_order_relaxed);\n"
         "        ms[c] = double(ns - prev_ns[c]) / 1e6 / double(frames);\n"
         "        n[c] = double(cn - prev_n[c]) / double(frames);\n"
         "        prev_ns[c] = ns;\n"
         "        prev_n[c] = cn;\n"
         "      }\n"
         "      const double frame_ms = double(now - last_us) / 1000.0 / double(frames);\n"
         "      REXGPU_INFO(\"mgr perf: {:.1f} fps, {:.1f} ms a frame; GPU thread per frame: idle (waiting for the game) {:.1f}, \"\n"
         "                  \"wait_reg_mem {:.1f} ({:.1f}x), GPU fences {:.1f}, submit {:.1f} ({:.1f}x), swap {:.1f}, \"\n"
         "                  \"draws (the rest) {:.1f} ({:.0f}; texture loads {:.1f} ({:.1f}), HD {:.1f} ({:.1f})), \"\n"
         "                  \"copies {:.1f} ({:.1f}), late readbacks {:.2f}, occlusion queries {:.1f} ({:.1f})\",\n"
         "                  1000.0 / frame_ms, frame_ms, ms[kIdle], ms[kWaitRegMem], n[kWaitRegMem], ms[kFenceWait],\n"
         "                  ms[kSubmit], n[kSubmit], ms[kSwap],\n"
         "                  std::max(0.0, frame_ms - ms[kIdle] - ms[kWaitRegMem] - ms[kFenceWait] - ms[kSubmit] -\n"
         "                                    ms[kSwap] - ms[kCopy] - ms[kOcclusion]),\n"
         "                  n[kDraw], ms[kTextureLoad], n[kTextureLoad], ms[kHd], n[kHd], ms[kCopy], n[kCopy],\n"
         "                  n[kReadbackLate], ms[kOcclusion], n[kOcclusion]);\n"
         "      last_us = now;\n"
         "      frames = 0;\n"
         "    }\n"
         "  }\n"
         "#if defined(__PROSPERO__)\n"
         "  {\n"
         "    // [mgr] The GPU thread is the game's limit: a core of its own (CPU 0,\n"
         "    // its twin CPU 1 left empty), the lane on CPU 4, the rest on 2-3 and 6-12 (moved\n"
         "    // when it is new: KeepOtherThreadsOn only touches changed ones).\n"
         "    static uint64_t cpus_us = 0;\n"
         "    const uint64_t now = rex::mgr_perf::NowUs();\n"
         "    if (!cpus_us) {\n"
         "      rex::frame_stats::scePthreadSetaffinity(pthread_self(), 1);\n"
         "      REXGPU_INFO(\"mgr: GPU thread on CPU 0, the lane on 4, the others on CPUs 2-3 and 6-12\");\n"
         "    }\n"
         "    if (!cpus_us || now - cpus_us >= 5000000) {\n"
         "      cpus_us = now;\n"
         "      rex::ps5diag::KeepOtherThreadsOn(0x1FCC, reinterpret_cast<uintptr_t>(pthread_self()), 0, 0);\n"
         "    }\n"
         "  }\n"
         "#endif\n"
         "  rex::frame_stats::NotePresent();  // [mgr] the frame rate counter (mgr_game_overlay.cpp)\n"
         "  rex::mgr_perf::Scope mgr_perf_swap(rex::mgr_perf::kSwap);\n")

    # Startup: the shader storage's pipelines were all created before the
    # game started (InitializeShaderStorage blocks the launch), one storage
    # that grows every session: 40 s and more of black screen at 5 a second.
    # With async_shader_compilation they go to the creation threads instead
    # (lowest priority) while the game starts; one drawn before it's built gets
    # what a new one gets: the placeholder at once, the real one queued.
    vpc2 = sdk / "src" / "graphics" / "vulkan" / "pipeline_cache.cpp"
    edit(vpc2,
         "  if (!pipeline_creations.empty()) {\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(creation_request_lock_);\n"
         "      startup_loading_ = true;\n",
         "  // [mgr] async: created at first use (see ci/patch_framework.py)\n"
         "  if (!pipeline_creations.empty() && REXCVAR_GET(async_shader_compilation) &&\n"
         "      !creation_threads_.empty()) {\n"
         "    REXGPU_INFO(\"{} stored graphics pipelines queued for the creation threads\", pipeline_creations.size());\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(creation_request_lock_);\n"
         "      for (PipelineCreationArguments& creation : pipeline_creations) {\n"
         "        creation.priority = pipeline_util::kPriorityLowest;\n"
         "        creation_queue_.push(creation);\n"
         "      }\n"
         "    }\n"
         "    creation_request_cond_.notify_all();\n"
         "    pipeline_creations.clear();\n"
         "  }\n"
         "  if (!pipeline_creations.empty()) {\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(creation_request_lock_);\n"
         "      startup_loading_ = true;\n")
    edit(vpc2,
         "    if (found_pipeline == VK_NULL_HANDLE) {\n"
         "      PipelineCreationArguments creation_arguments;\n",
         "    if (found_pipeline == VK_NULL_HANDLE && use_async) {\n"
         "      // [mgr] not built yet (a stored one's first use, or one still being built): its\n"
         "      // draws are skipped until a creation thread has it - the real one queued once, at\n"
         "      // the draw's priority. Nothing is compiled here, on the GPU thread\n"
         "      if (!it->second.is_placeholder.exchange(true, std::memory_order_acq_rel)) {\n"
         "        PipelineCreationArguments creation_arguments_real;\n"
         "        if (TryGetPipelineCreationArgumentsForDescription(description, &*it, creation_arguments_real)) {\n"
         "          creation_arguments_real.priority = async_priority;\n"
         "          {\n"
         "            std::lock_guard<std::mutex> lock(creation_request_lock_);\n"
         "            creation_queue_.push(creation_arguments_real);\n"
         "          }\n"
         "          creation_request_cond_.notify_one();\n"
         "        } else {\n"
         "          it->second.is_placeholder.store(false, std::memory_order_release);\n"
         "        }\n"
         "      }\n"
         "      found_pipeline = it->second.pipeline.load(std::memory_order_acquire);\n"
         "      if (found_pipeline == VK_NULL_HANDLE && it->second.is_placeholder.load(std::memory_order_acquire)) {\n"
         "        pipeline_out = VK_NULL_HANDLE;\n"
         "        pipeline_layout_out = nullptr;\n"
         "        if (pipeline_handle_out) {\n"
         "          *pipeline_handle_out = &it->second;\n"
         "        }\n"
         "        return true;\n"
         "      }\n"
         "    }\n"
         "    if (found_pipeline == VK_NULL_HANDLE) {\n"
         "      PipelineCreationArguments creation_arguments;\n")
    # [mgr] Every submission's end built the whole creation queue on the GPU thread
    # (CreateQueuedPipelinesOnProcessorThread) and then waited for the creation threads'
    # pipelines in flight, so the async path above stalled the frame anyway: with an empty
    # cache (a new install) every new area's burst of pipelines froze the picture. Found in
    # PROTOTYPE: ReEvolution (100-650 ms, all in "submit"). With async compilation the queue
    # is left to the creation threads.
    edit(vpc2,
         "    if (startup_loading) {\n"
         "      creation_request_cond_.notify_one();\n"
         "    } else {\n",
         "    if (startup_loading || REXCVAR_GET(async_shader_compilation)) {  // [mgr]\n"
         "      creation_request_cond_.notify_one();\n"
         "    } else {\n")
    # [mgr] The DualSense light bar in the game's own colour (mgr_game_overlay.cpp: health,
    # hits, Zandatsu, Ripper Mode) instead of GTA IV's episode colours and police lights, and
    # MGR's triggers: L2 (Blade Mode) a weight to pull, R2 (Ninja Run) a light pedal, instead
    # of GTA IV's aim and gun.
    sfh = sdk / "include" / "rex" / "input" / "sony_feedback.h"
    sfc = sdk / "src" / "input" / "sony_feedback.cpp"
    edit(sfh,
         "  uint32_t context_identity = 0;\n};\n",
         "  uint32_t context_identity = 0;\n"
         "  bool has_color = false;  // [mgr] the light bar's colour, from the game\n"
         "  std::array<uint8_t, 3> color{};\n"
         "  float left_resistance = -1, right_resistance = -1;  // [mgr] 0..1 (below 0: GTA IV's)\n};\n")
    edit(sfc,
         "  if (slot.game.wanted > 0 && now_ms >= slot.wanted_started_ms) {\n",
         "  if (slot.game.has_color) {  // [mgr]\n"
         "    output.color = slot.game.color;\n"
         "  } else if (slot.game.wanted > 0 && now_ms >= slot.wanted_started_ms) {\n")
    edit(sfc,
         "    } else if (slot.game.trigger_context == TriggerContext::kWeapon) {\n",
         "    } else if (slot.game.left_resistance >= 0 || slot.game.right_resistance >= 0) {  // [mgr]\n"
         "      if (slot.game.left_resistance > 0) {\n"
         "        const float f = intensity * slot.game.left_resistance;\n"
         "        output.left = Resistance(40, Force(f)), output.left_feel = {Feel::kAim, f};\n"
         "      }\n"
         "      if (slot.game.right_resistance > 0) {\n"
         "        const float f = intensity * slot.game.right_resistance;\n"
         "        output.right = Resistance(20, Force(f)), output.right_feel = {Feel::kPedal, f};\n"
         "      }\n"
         "    } else if (slot.game.trigger_context == TriggerContext::kWeapon) {\n")
    # [mgr] A shader met for the first time was translated (Xenos microcode to SPIR-V) on the
    # GPU thread in the middle of its draw: about 25 ms each with the EDRAM emulated (612 in
    # 1924 ms on 8 threads at startup), so a new area's ten or so new shaders held one frame
    # 100-300 ms (mgr_015.log: every hitch of a fresh-cache run in "draws", none in submit
    # after the change above). Now worker threads translate them; the draw is skipped until
    # its shaders are in, as a draw waiting for its pipeline is, and the GPU thread does only
    # what it owns (the shader module and the binding layouts) once a translation is done.
    # A shader's translations go to one worker at a time (as at startup).
    vpch = sdk / "include" / "rex" / "graphics" / "vulkan" / "pipeline_cache.h"
    edit(vpch,
         "  bool EnsureShadersTranslated(VulkanShader::VulkanTranslation* vertex_shader,\n"
         "                               VulkanShader::VulkanTranslation* pixel_shader);\n",
         "  bool EnsureShadersTranslated(VulkanShader::VulkanTranslation* vertex_shader,\n"
         "                               VulkanShader::VulkanTranslation* pixel_shader);\n"
         "  // [mgr] true while either is being translated on a worker (queued if new): skip the draw\n"
         "  bool MgrTranslationPending(VulkanShader::VulkanTranslation* vertex_shader,\n"
         "                             VulkanShader::VulkanTranslation* pixel_shader);\n")
    edit(vpch,
         "  std::unique_ptr<SpirvShaderTranslator> shader_translator_;\n",
         "  std::unique_ptr<SpirvShaderTranslator> shader_translator_;\n"
         "  // [mgr] Shader translation on worker threads (MgrTranslationPending).\n"
         "  void MgrTranslationThread(SpirvShaderTranslator* translator);\n"
         "  void MgrStopTranslationThreads();\n"
         "  std::mutex mgr_translation_lock_;\n"
         "  std::condition_variable mgr_translation_cond_;\n"
         "  std::deque<VulkanShader::VulkanTranslation*> mgr_translation_queue_;\n"
         "  std::vector<VulkanShader::VulkanTranslation*> mgr_translation_done_;\n"
         "  std::set<const void*> mgr_translation_busy_shaders_;\n"
         "  bool mgr_translation_shutdown_ = false;\n"
         "  // (the processor thread's own)\n"
         "  std::set<VulkanShader::VulkanTranslation*> mgr_translation_in_flight_;\n"
         "  std::vector<std::unique_ptr<SpirvShaderTranslator>> mgr_translation_translators_;\n"
         "  std::vector<std::unique_ptr<rex::thread::Thread>> mgr_translation_threads_;\n")
    edit(vpc2,
         "#include <rex/ui/vulkan/util.h>\n"
         "\n"
         "REXCVAR_DEFINE_INT32(\n"
         "    vulkan_pipeline_creation_threads,",
         "#include <rex/ui/vulkan/util.h>\n"
         "\n"
         "REXCVAR_DEFINE_INT32(mgr_shader_translation_threads, 2, \"GPU/Vulkan\",\n"
         "                     \"Threads translating new shaders while their draws wait (0: on the GPU thread, \"\n"
         "                     \"in the draw)\")\n"
         "    .range(0, 8);\n"
         "\n"
         "REXCVAR_DEFINE_INT32(\n"
         "    vulkan_pipeline_creation_threads,")
    edit(vpc2,
         "void VulkanPipelineCache::Shutdown() {\n",
         "void VulkanPipelineCache::MgrTranslationThread(SpirvShaderTranslator* translator) {\n"
         "  for (;;) {\n"
         "    VulkanShader::VulkanTranslation* job = nullptr;\n"
         "    {\n"
         "      std::unique_lock<std::mutex> lock(mgr_translation_lock_);\n"
         "      for (;;) {\n"
         "        if (mgr_translation_shutdown_) return;\n"
         "        auto it = std::find_if(mgr_translation_queue_.begin(), mgr_translation_queue_.end(),\n"
         "                               [this](VulkanShader::VulkanTranslation* t) {\n"
         "                                 return !mgr_translation_busy_shaders_.count(&t->shader());\n"
         "                               });\n"
         "        if (it != mgr_translation_queue_.end()) {\n"
         "          job = *it;\n"
         "          mgr_translation_queue_.erase(it);\n"
         "          mgr_translation_busy_shaders_.insert(&job->shader());\n"
         "          break;\n"
         "        }\n"
         "        mgr_translation_cond_.wait(lock);\n"
         "      }\n"
         "    }\n"
         "    translator->TranslateAnalyzedShader(*job);\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(mgr_translation_lock_);\n"
         "      mgr_translation_busy_shaders_.erase(&job->shader());\n"
         "      mgr_translation_done_.push_back(job);\n"
         "    }\n"
         "    mgr_translation_cond_.notify_all();\n"
         "  }\n"
         "}\n"
         "\n"
         "void VulkanPipelineCache::MgrStopTranslationThreads() {\n"
         "  {\n"
         "    std::lock_guard<std::mutex> lock(mgr_translation_lock_);\n"
         "    mgr_translation_shutdown_ = true;\n"
         "  }\n"
         "  mgr_translation_cond_.notify_all();\n"
         "  for (const auto& thread : mgr_translation_threads_) rex::thread::Wait(thread.get(), false);\n"
         "  mgr_translation_threads_.clear();\n"
         "  mgr_translation_translators_.clear();\n"
         "  mgr_translation_queue_.clear();\n"
         "  mgr_translation_done_.clear();\n"
         "  mgr_translation_busy_shaders_.clear();\n"
         "  mgr_translation_in_flight_.clear();\n"
         "}\n"
         "\n"
         "bool VulkanPipelineCache::MgrTranslationPending(VulkanShader::VulkanTranslation* vertex_shader,\n"
         "                                                VulkanShader::VulkanTranslation* pixel_shader) {\n"
         "  const int32_t threads = REXCVAR_GET(mgr_shader_translation_threads);\n"
         "  if (threads <= 0 || mgr_translation_shutdown_) return false;\n"
         "  if (mgr_translation_threads_.empty()) {\n"
         "    const ui::vulkan::VulkanDevice* const device = command_processor_.GetVulkanDevice();\n"
         "    const bool fsi = render_target_cache_.GetPath() == RenderTargetCache::Path::kPixelShaderInterlock;\n"
         "    for (int32_t i = 0; i < threads; ++i) {\n"
         "      mgr_translation_translators_.push_back(std::make_unique<SpirvShaderTranslator>(\n"
         "          SpirvShaderTranslator::Features(device), render_target_cache_.msaa_2x_attachments_supported(),\n"
         "          render_target_cache_.msaa_2x_no_attachments_supported(), fsi,\n"
         "          render_target_cache_.draw_resolution_scale_x(), render_target_cache_.draw_resolution_scale_y()));\n"
         "      SpirvShaderTranslator* translator = mgr_translation_translators_.back().get();\n"
         "      mgr_translation_threads_.push_back(\n"
         "          rex::thread::Thread::Create({}, [this, translator]() { MgrTranslationThread(translator); }));\n"
         "      mgr_translation_threads_.back()->set_name(\"Vulkan Shader Translation\");\n"
         "    }\n"
         "    REXGPU_INFO(\"mgr: new shaders translated on {} threads while their draws wait\", threads);\n"
         "  }\n"
         "  if (!mgr_translation_in_flight_.empty()) {\n"
         "    std::vector<VulkanShader::VulkanTranslation*> done;\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(mgr_translation_lock_);\n"
         "      done.swap(mgr_translation_done_);\n"
         "    }\n"
         "    for (VulkanShader::VulkanTranslation* translation : done) {\n"
         "      mgr_translation_in_flight_.erase(translation);\n"
         "      // (translated already: its module and binding layouts, here on the processor thread)\n"
         "      TranslateAnalyzedShader(*shader_translator_, *translation);\n"
         "    }\n"
         "  }\n"
         "  bool pending = false;\n"
         "  for (VulkanShader::VulkanTranslation* translation : {vertex_shader, pixel_shader}) {\n"
         "    if (!translation) continue;\n"
         "    if (mgr_translation_in_flight_.count(translation)) {\n"
         "      pending = true;\n"
         "      continue;\n"
         "    }\n"
         "    if (translation->is_translated()) continue;\n"
         "    if (!translation->shader().is_ucode_analyzed()) {\n"
         "      translation->shader().AnalyzeUcode(ucode_disasm_buffer_);\n"
         "    }\n"
         "    mgr_translation_in_flight_.insert(translation);\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(mgr_translation_lock_);\n"
         "      mgr_translation_queue_.push_back(translation);\n"
         "    }\n"
         "    mgr_translation_cond_.notify_one();\n"
         "    pending = true;\n"
         "  }\n"
         "  return pending;\n"
         "}\n"
         "\n"
         "void VulkanPipelineCache::Shutdown() {\n"
         "  MgrStopTranslationThreads();  // [mgr]\n")
    edit(vcp,
         "    if (!pipeline_cache_->EnsureShadersTranslated(vertex_shader_translation,\n"
         "                                                  pixel_shader_translation)) {\n"
         "      return draw_fail(\"shader_translation\");\n"
         "    }\n",
         "    // [mgr] a new shader is translated on a worker: the draw waits, as for its pipeline\n"
         "    if (pipeline_cache_->MgrTranslationPending(vertex_shader_translation, pixel_shader_translation)) {\n"
         "      frame_used_async_placeholder_pipeline_ = true;\n"
         "      ++frame_flow_draw_placeholders_;\n"
         "      return true;\n"
         "    }\n"
         "    if (!pipeline_cache_->EnsureShadersTranslated(vertex_shader_translation,\n"
         "                                                  pixel_shader_translation)) {\n"
         "      return draw_fail(\"shader_translation\");\n"
         "    }\n")
    # [mgr] New pipelines the same way: queued for the creation threads, the draws skipped until
    # one is built - depth-only ones too (no pixel shader: shadows, the depth pass), which were
    # built on the GPU thread, as was the placeholder every other one got first. 529 of the 1014
    # pipelines of the first chapter 1 after a fresh install were built there (mgr_002.log),
    # 184 in the minute from the cutscene to gameplay: the freezes.
    edit(vpc2,
         "  bool use_async = REXCVAR_GET(async_shader_compilation) && !creation_threads_.empty() &&\n"
         "                   pixel_shader && placeholder_pixel_shader_ != VK_NULL_HANDLE;\n",
         "  bool use_async = REXCVAR_GET(async_shader_compilation) && !creation_threads_.empty();\n")
    edit(vpc2,
         "  bool queued_async_creation = false;\n"
         "  if (use_async) {\n"
         "    creation_arguments_real.priority = async_priority;\n"
         "    PipelineCreationArguments creation_arguments_placeholder;\n"
         "    if (TryGetPipelineCreationArgumentsForDescription(description, &pipeline,\n"
         "                                                      creation_arguments_placeholder, true)) {\n"
         "      pipeline.second.is_placeholder.store(true, std::memory_order_release);\n"
         "      if (EnsurePipelineCreated(creation_arguments_placeholder, placeholder_pixel_shader_)) {\n"
         "        {\n"
         "          std::lock_guard<std::mutex> lock(creation_request_lock_);\n"
         "          creation_queue_.push(creation_arguments_real);\n"
         "        }\n"
         "        creation_request_cond_.notify_one();\n"
         "        queued_async_creation = true;\n"
         "      } else {\n"
         "        pipeline.second.is_placeholder.store(false, std::memory_order_release);\n"
         "      }\n"
         "    }\n"
         "  }\n",
         "  bool queued_async_creation = false;\n"
         "  if (use_async) {\n"
         "    // [mgr] queued, no placeholder built: the draws are skipped until it's ready\n"
         "    creation_arguments_real.priority = async_priority;\n"
         "    pipeline.second.is_placeholder.store(true, std::memory_order_release);\n"
         "    {\n"
         "      std::lock_guard<std::mutex> lock(creation_request_lock_);\n"
         "      creation_queue_.push(creation_arguments_real);\n"
         "    }\n"
         "    creation_request_cond_.notify_one();\n"
         "    queued_async_creation = true;\n"
         "  }\n")
    edit(vpc2,
         "  last_pipeline_ = &pipeline;\n"
         "  pipeline_out = pipeline.second.pipeline.load(std::memory_order_acquire);\n"
         "  pipeline_layout_out = pipeline.second.pipeline_layout.load(std::memory_order_acquire);\n"
         "  if (pipeline_handle_out) {\n"
         "    *pipeline_handle_out = &pipeline.second;\n"
         "  }\n"
         "  return pipeline_out != VK_NULL_HANDLE && pipeline_layout_out != nullptr;\n",
         "  last_pipeline_ = &pipeline;\n"
         "  pipeline_out = pipeline.second.pipeline.load(std::memory_order_acquire);\n"
         "  pipeline_layout_out = pipeline.second.pipeline_layout.load(std::memory_order_acquire);\n"
         "  if (pipeline_handle_out) {\n"
         "    *pipeline_handle_out = &pipeline.second;\n"
         "  }\n"
         "  // [mgr] (one being built: the draw is skipped, not failed)\n"
         "  return (pipeline_out != VK_NULL_HANDLE && pipeline_layout_out != nullptr) ||\n"
         "         (queued_async_creation && pipeline_out == VK_NULL_HANDLE);\n")

    # The driver's compiled pipelines kept across sessions (a VkPipelineCache
    # in <cache>/shaders, as gta4-ps5's own renderer keeps one): without it
    # every session compiled every pipeline again, and the stutters in
    # gameplay were those compiles (mgr_008.log: each drop a burst of
    # "Creating graphics pipeline state"). Loaded at start, NEVER saved in play: the periodic
    # save (vkGetPipelineCacheData of 21 MB + a 21 MB write to the USB drive) was a ~300 ms
    # hitch every time, whatever the number of new pipelines (mgr_025 17:00:06 / 17:01:06 /
    # 17:02:16; mgr_026 17:24:19 in play and 17:26:09 in a cutscene, still there with the
    # saver thread off CPU 0). Pipelines made since are kept by RADV's own disk cache
    # (radv-shader-cache/mesa_shader_cache_db, written incrementally in small entries), so the
    # next session's creations of them are cache hits; the pipeline descriptions themselves are
    # stored by the storage write thread (.xpso) as before.
    edit(vpc2,
         "namespace rex::graphics::vulkan {\n",
         "namespace rex::graphics::vulkan {\n\n"
         "// [mgr] the driver's pipeline cache, kept across sessions (ci/patch_framework.py)\n"
         "namespace {\n"
         "VkPipelineCache mgr_vk_cache = VK_NULL_HANDLE;\n"
         "const ui::vulkan::VulkanDevice* mgr_vk_cache_device = nullptr;\n"
         "std::string mgr_vk_cache_path;\n"
         "void MgrOpenPipelineCache(const ui::vulkan::VulkanDevice* device, const std::filesystem::path& path) {\n"
         "  if (mgr_vk_cache != VK_NULL_HANDLE || !device) return;\n"
         "  std::vector<uint8_t> data;\n"
         "  if (std::FILE* f = std::fopen(path.string().c_str(), \"rb\")) {\n"
         "    std::fseek(f, 0, SEEK_END);\n"
         "    const long size = std::ftell(f);\n"
         "    std::fseek(f, 0, SEEK_SET);\n"
         "    if (size > 0 && size < (256l << 20)) {\n"
         "      data.resize(size_t(size));\n"
         "      if (std::fread(data.data(), 1, data.size(), f) != data.size()) data.clear();\n"
         "    }\n"
         "    std::fclose(f);\n"
         "  }\n"
         "  VkPipelineCacheCreateInfo info = {VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO};\n"
         "  info.initialDataSize = data.size();\n"
         "  info.pInitialData = data.empty() ? nullptr : data.data();\n"
         "  const auto& dfn = device->functions();\n"
         "  if (dfn.vkCreatePipelineCache(device->device(), &info, nullptr, &mgr_vk_cache) != VK_SUCCESS) {\n"
         "    info.initialDataSize = 0;\n"
         "    info.pInitialData = nullptr;\n"
         "    if (dfn.vkCreatePipelineCache(device->device(), &info, nullptr, &mgr_vk_cache) != VK_SUCCESS)\n"
         "      mgr_vk_cache = VK_NULL_HANDLE;\n"
         "  }\n"
         "  mgr_vk_cache_device = device;\n"
         "  mgr_vk_cache_path = path.string();\n"
         "  REXGPU_INFO(\"mgr: Vulkan pipeline cache {} ({} KB) at {}\", mgr_vk_cache ? \"open\" : \"unavailable\",\n"
         "              data.size() >> 10, mgr_vk_cache_path);\n"
         "}\n"
         "}  // namespace\n\n"
         "")
    edit(vpc2, "#include <algorithm>\n",
         "#include <algorithm>\n#include <cstdio>\n#include <filesystem>\n#include <thread>\n")
    edit(vpc2,
         "  auto shader_storage_root = cache_root / \"shaders\";\n"
         "  auto shader_storage_shareable_root = shader_storage_root / \"shareable\";\n",
         "  auto shader_storage_root = cache_root / \"shaders\";\n"
         "  auto shader_storage_shareable_root = shader_storage_root / \"shareable\";\n"
         "  {\n"
         "    std::error_code mgr_ec;\n"
         "    std::filesystem::create_directories(shader_storage_root, mgr_ec);\n"
         "    MgrOpenPipelineCache(command_processor_.GetVulkanDevice(),\n"
         "                         shader_storage_root / fmt::format(\"{:08X}.vk-pipelines.bin\", title_id));\n"
         "  }\n")
    edit(vpc2,
         "  VkResult create_result = dfn.vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1,\n"
         "                                                         &pipeline_create_info, nullptr, &pipeline);\n",
         "  VkResult create_result = dfn.vkCreateGraphicsPipelines(device, mgr_vk_cache, 1,\n"
         "                                                         &pipeline_create_info, nullptr, &pipeline);\n")

    # The pipeline description storage (<title>.fsi.vk.xpso) held 229 pipelines
    # in every session since the first ones, though each session made new ones
    # (mgr_001.log, 20:22): so every session translated and built those again
    # mid-game. How many were read, kept and written, for the log; and the
    # files seeked to their end before the writer appends.
    edit(vpc2,
         "      pipeline_stored_descriptions.resize(pipeline_storage_kept_count);\n",
         "      pipeline_stored_descriptions.resize(pipeline_storage_kept_count);\n"
         "      REXGPU_INFO(\"mgr: pipeline storage: {} read, {} kept, {} unsupported, {} corrupted\",\n"
         "                  pipeline_storage_read_count, pipeline_storage_kept_count,\n"
         "                  pipeline_storage_skipped_unsupported_count, pipeline_storage_skipped_corrupted_count);\n")
    edit(vpc2,
         "    rex::filesystem::TruncateStdioFile(shader_storage_file_, shader_storage_valid_bytes);\n",
         "    rex::filesystem::TruncateStdioFile(shader_storage_file_, shader_storage_valid_bytes);\n"
         "    rex::filesystem::Seek(shader_storage_file_, 0, SEEK_END);  // [mgr] (for the writer)\n"
         "    REXGPU_INFO(\"mgr: shader storage: {} KB of shaders\", shader_storage_valid_bytes >> 10);\n")
    edit(vpc2,
         "  shader_storage_cache_root_ = cache_root;\n  shader_storage_title_id_ = title_id;\n",
         "  rex::filesystem::Seek(pipeline_storage_file_, 0, SEEK_END);  // [mgr] (for the writer)\n"
         "  shader_storage_cache_root_ = cache_root;\n  shader_storage_title_id_ = title_id;\n")
    edit(vpc2,
         "    if (write_pipeline) {\n"
         "      assert_not_null(pipeline_storage_file_);\n"
         "      fwrite(&pipeline_description, sizeof(pipeline_description), 1, pipeline_storage_file_);\n"
         "    }\n",
         "    if (write_pipeline) {\n"
         "      assert_not_null(pipeline_storage_file_);\n"
         "      const size_t mgr_written =\n"
         "          fwrite(&pipeline_description, sizeof(pipeline_description), 1, pipeline_storage_file_);\n"
         "      static uint32_t mgr_writes = 0, mgr_failed = 0;\n"
         "      mgr_failed += mgr_written != 1;\n"
         "      if ((++mgr_writes % 50) == 1 || mgr_written != 1)\n"
         "        REXGPU_INFO(\"mgr: pipeline storage: {} written this session ({} failed)\", mgr_writes, mgr_failed);\n"
         "    }\n")

    # The stored shaders were translated one at a time on the GPU thread, before
    # the game's main thread is even resumed (rex_app.cpp: blocking): the wait
    # after PLAY grew with every shader the player had met. Now on several
    # threads, each with a translator of its own and a shader's modifications
    # on one thread, as the D3D12 cache does; the shader modules and binding
    # layouts after, on this thread (TranslateAnalyzedShader skips the
    # translator for a translation that's done).
    edit(vpc2, "#include <array>\n", "#include <array>\n#include <chrono>\n")
    edit(vpc2,
         "  if (!translator.TranslateAnalyzedShader(translation)) {\n",
         "  if (translation.is_translated() ? !translation.is_valid()\n"
         "                                  : !translator.TranslateAnalyzedShader(translation)) {\n")
    edit(vpc2,
         "  // Translate shader modifications needed for stored pipelines.\n"
         "  for (const std::pair<uint64_t, uint64_t>& translation_needed : shader_translations_needed) {\n"
         "    auto shader_it = shaders_.find(translation_needed.first);\n"
         "    if (shader_it == shaders_.end()) {\n"
         "      continue;\n"
         "    }\n"
         "    auto* shader = shader_it->second;\n"
         "    if (!shader->is_ucode_analyzed()) {\n"
         "      shader->AnalyzeUcode(ucode_disasm_buffer_);\n"
         "    }\n"
         "    bool translation_is_new = false;\n"
         "    auto* translation = static_cast<VulkanShader::VulkanTranslation*>(\n"
         "        shader->GetOrCreateTranslation(translation_needed.second, &translation_is_new));\n"
         "    if (!translation->is_translated() &&\n"
         "        !TranslateAnalyzedShader(*shader_translator_, *translation)) {\n"
         "      if (translation_is_new) {\n"
         "        shader->DestroyTranslation(translation_needed.second);\n"
         "      }\n"
         "    }\n"
         "  }\n",
         "  // Translate shader modifications needed for stored pipelines.\n"
         "  // [mgr] on several threads (ci/patch_framework.py)\n"
         "  {\n"
         "    const auto mgr_start = std::chrono::steady_clock::now();\n"
         "    struct MgrTranslation {\n"
         "      VulkanShader* shader;\n"
         "      uint64_t modification;\n"
         "      VulkanShader::VulkanTranslation* translation;\n"
         "      bool is_new;\n"
         "    };\n"
         "    std::vector<MgrTranslation> mgr_jobs;  // (a shader's together: the set's order)\n"
         "    for (const std::pair<uint64_t, uint64_t>& translation_needed : shader_translations_needed) {\n"
         "      auto shader_it = shaders_.find(translation_needed.first);\n"
         "      if (shader_it == shaders_.end()) {\n"
         "        continue;\n"
         "      }\n"
         "      auto* shader = shader_it->second;\n"
         "      if (!shader->is_ucode_analyzed()) {\n"
         "        shader->AnalyzeUcode(ucode_disasm_buffer_);\n"
         "      }\n"
         "      bool translation_is_new = false;\n"
         "      auto* translation = static_cast<VulkanShader::VulkanTranslation*>(\n"
         "          shader->GetOrCreateTranslation(translation_needed.second, &translation_is_new));\n"
         "      if (!translation->is_translated()) {\n"
         "        mgr_jobs.push_back({shader, translation_needed.second, translation, translation_is_new});\n"
         "      }\n"
         "    }\n"
         "    std::vector<size_t> mgr_groups;  // (where each shader's start, and the end)\n"
         "    for (size_t i = 0; i < mgr_jobs.size(); ++i) {\n"
         "      if (!i || mgr_jobs[i].shader != mgr_jobs[i - 1].shader) mgr_groups.push_back(i);\n"
         "    }\n"
         "    mgr_groups.push_back(mgr_jobs.size());\n"
         "    std::atomic<size_t> mgr_next_group(0);\n"
         "    auto mgr_translate = [&](SpirvShaderTranslator& translator) {\n"
         "      for (size_t g; (g = mgr_next_group.fetch_add(1)) + 1 < mgr_groups.size();) {\n"
         "        for (size_t i = mgr_groups[g]; i < mgr_groups[g + 1]; ++i) {\n"
         "          translator.TranslateAnalyzedShader(*mgr_jobs[i].translation);\n"
         "        }\n"
         "      }\n"
         "    };\n"
         "    const uint32_t mgr_cpus = std::max(rex::thread::logical_processor_count(), uint32_t(2));\n"
         "    const size_t mgr_threads =\n"
         "        std::min<size_t>(std::min<uint32_t>(mgr_cpus - 1, 8), mgr_groups.size() - 1);\n"
         "    if (mgr_threads > 1) {\n"
         "      const ui::vulkan::VulkanDevice* const mgr_device = command_processor_.GetVulkanDevice();\n"
         "      const bool mgr_fsi =\n"
         "          render_target_cache_.GetPath() == RenderTargetCache::Path::kPixelShaderInterlock;\n"
         "      std::vector<std::unique_ptr<SpirvShaderTranslator>> mgr_translators;\n"
         "      std::vector<std::unique_ptr<rex::thread::Thread>> mgr_workers;\n"
         "      for (size_t i = 1; i < mgr_threads; ++i) {\n"
         "        mgr_translators.push_back(std::make_unique<SpirvShaderTranslator>(\n"
         "            SpirvShaderTranslator::Features(mgr_device),\n"
         "            render_target_cache_.msaa_2x_attachments_supported(),\n"
         "            render_target_cache_.msaa_2x_no_attachments_supported(), mgr_fsi,\n"
         "            render_target_cache_.draw_resolution_scale_x(),\n"
         "            render_target_cache_.draw_resolution_scale_y()));\n"
         "        SpirvShaderTranslator* translator = mgr_translators.back().get();\n"
         "        mgr_workers.push_back(\n"
         "            rex::thread::Thread::Create({}, [&mgr_translate, translator]() { mgr_translate(*translator); }));\n"
         "        mgr_workers.back()->set_name(\"Vulkan Shader Translation\");\n"
         "      }\n"
         "      mgr_translate(*shader_translator_);\n"
         "      for (const auto& worker : mgr_workers) rex::thread::Wait(worker.get(), false);\n"
         "    } else {\n"
         "      mgr_translate(*shader_translator_);\n"
         "    }\n"
         "    for (const MgrTranslation& job : mgr_jobs) {\n"
         "      if (!TranslateAnalyzedShader(*shader_translator_, *job.translation) && job.is_new) {\n"
         "        job.shader->DestroyTranslation(job.modification);\n"
         "      }\n"
         "    }\n"
         "    REXGPU_INFO(\"mgr: shader storage: {} shader translations for the stored pipelines in {} ms ({} threads)\",\n"
         "                mgr_jobs.size(),\n"
         "                std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() -\n"
         "                                                                      mgr_start)\n"
         "                    .count(),\n"
         "                std::max<size_t>(mgr_threads, 1));\n"
         "  }\n")

    # The storage files stay open all session, and the PS5 ends the game
    # without closing them: what they gained never reached the drive
    # (mgr_002.log: 101 pipelines written, 229 read at the next start, as in
    # every session since the first). Each flush now goes to the drive.
    edit(vpc2, "#include <algorithm>\n#include <cstdio>\n",
         "#include <algorithm>\n#include <cstdio>\n#include <unistd.h>\n")
    edit(vpc2,
         "      fflush(shader_storage_file_);\n",
         "      fflush(shader_storage_file_);\n      fsync(fileno(shader_storage_file_));  // [mgr]\n")
    edit(vpc2,
         "      fflush(pipeline_storage_file_);\n",
         "      fflush(pipeline_storage_file_);\n      fsync(fileno(pipeline_storage_file_));  // [mgr]\n")

    # The next frame may be in the next buffer (Xenia's data-aware search).
    xt = xc.read_text()
    a = xt.index("void XmaContext::Decode(XMA_CONTEXT_DATA* data) {\n")
    b = xt.index("void XmaContext::ConvertFrame(")
    body = xt[a:b]
    if "mgr_next_read_offset" in body:
        print(f"already  {xc} (Decode)")
        return
    old_buf = "  uint8_t* current_input_buffer = GetCurrentInputBuffer(data);\n"
    new_buf = (old_buf +
        "  // [mgr] Read offset of the next frame from packet `index` on, which\n"
        "  // past the end of this buffer is in the next one (as Xenia).\n"
        "  const auto mgr_next_read_offset = [&](uint32_t index, uint32_t count) -> uint32_t {\n"
        "    uint8_t buffer = data->current_buffer;\n"
        "    if (index >= count) {\n"
        "      buffer ^= 1;\n      index -= count;\n"
        "    }\n"
        "    if (!data->IsInputBufferValid(buffer) || !data->GetInputBufferAddress(buffer)) {\n"
        "      return kBitsPerPacketHeader;\n    }\n"
        "    return GetNextPacketReadOffset(\n"
        "        memory()->TranslatePhysical(data->GetInputBufferAddress(buffer)), index,\n"
        "        data->GetInputBufferPacketCount(buffer));\n"
        "  };\n")
    old_ff = ("    uint32_t next_input_offset =\n"
              "        GetNextPacketReadOffset(current_input_buffer, packet_index + 1, current_input_packet_count);\n"
              "    if (next_input_offset == kBitsPerPacketHeader) {\n"
              "      SwapInputBuffer(data);\n    }\n")
    new_ff = ("    uint32_t next_input_offset =\n"
              "        mgr_next_read_offset(packet_index + 1, current_input_packet_count);\n"
              "    if (uint32_t(packet_index + 1) >= current_input_packet_count ||\n"
              "        next_input_offset == kBitsPerPacketHeader) {\n"
              "      SwapInputBuffer(data);\n    }\n")
    old_last = ("  uint32_t next_input_offset =\n"
                "      GetNextPacketReadOffset(current_input_buffer, next_packet_index, current_input_packet_count);\n\n"
                "  if (next_input_offset == kBitsPerPacketHeader) {\n"
                "    SwapInputBuffer(data);\n")
    new_last = ("  uint32_t next_input_offset =\n"
                "      mgr_next_read_offset(next_packet_index, current_input_packet_count);\n\n"
                "  if (next_packet_index >= current_input_packet_count ||\n"
                "      next_input_offset == kBitsPerPacketHeader) {\n"
                "    SwapInputBuffer(data);\n  }\n"
                "  if (next_input_offset == kBitsPerPacketHeader) {\n")
    for old, new in ((old_buf, new_buf), (old_ff, new_ff), (old_last, new_last)):
        if body.count(old) != 1:
            sys.exit(f"patch_framework: expected 1 of {old!r} in Decode, found {body.count(old)}")
        body = body.replace(old, new)
    n = [0]
    def site(m):
        n[0] += 1
        return f"data->error_status = 4, ++mgr_xma_err[{n[0] - 1}];"
    body = re.sub(r"data->error_status = 4;", site, body)
    if not 8 <= n[0] <= 16:
        sys.exit(f"patch_framework: {n[0]} error sites in Decode")
    xc.write_text(xt[:a] + body + xt[b:])
    print(f"patched  {xc} (Decode: next-buffer search, {n[0]} error sites counted)")
    draw_profile(sdk)
    # wait_diag(sdk) is not applied in the user's build (release candidate): it found what it was for
    # (the checkpoint pause is the game's loop step, sub_82BFF9F8 on thread F8000158).
    overwrite_in_place(sdk)
    # The framework speed pack (Downloads/Recomps/speed-pack): unchanged constant writes skipped,
    # WAIT_REG_MEM polled before sleeping, the submit thread (CPU 5: the lane's twin, free here)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import fw_speed_pack
    # skip_default=0 and submit_default=False (supervisor order 2026-11-06): the skip and the submit
    # thread are OFF until proven; the submit thread's ordering against resolves and EDRAM copies is
    # not yet proven in code (Driver SF's picture broke with the same package on).
    fw_speed_pack.apply(sdk, edit, cpu=5, skip_default=0, submit_default=False,
                        perf_scope="rex::mgr_perf::Scope mgr_perf_submit_wait(rex::mgr_perf::kSubmit);")


def overwrite_in_place(sdk):
    """A save's file overwritten in place: truncated, not deleted and created again.

    mgr_025 17:02:30: the game's save writes Drive02000016:\\GameData_00 with NtCreateFile
    disposition 5 (FILE_OVERWRITE_IF). OpenFile took 290 ms between "VFS resolved" (.517) and
    "Added handle" (.806); the 28 KB write after it took under 2 ms. The game's loop thread waits
    for it, and the main thread waits for that one: a 302 ms frame. Stock OpenFile overwrites by
    Entry::Delete (std::filesystem::remove of the host file) and CreatePath (fopen "wb" + fclose +
    stat of a new file) before FileHandle::OpenExisting. On the PS5's /mnt/ext1 (a USB drive,
    exFAT: homebrew guides) that is a directory entry removed and another one made, each a
    metadata write of the directory and the allocation table. HostPathEntry::Truncate (fopen "wb"
    of the existing file) gives the same file, empty, under the same entry: only its clusters
    freed, no directory entry touched. The stock code already uses it when the delete fails; this
    tries it first and keeps delete + create as the fallback (entries without Truncate: other
    devices, read-only, directories). The game sees the same thing: FileAction::kOverwritten, an
    empty file opened with the access it asked for.
    """
    vfs = sdk / "src" / "filesystem" / "virtual_file_system.cpp"
    edit(vfs,
         "        // Overwrite by delete + recreate, or truncate if delete fails\n"
         "        // (host file may be briefly locked by cloud sync, AV, etc.).\n"
         "        if (entry->Delete()) {\n"
         "          entry = nullptr;\n"
         "        } else if (!entry->Truncate()) {\n"
         "          return X_STATUS_ACCESS_DENIED;\n"
         "        }\n",
         "        // [mgr] Overwrite by truncating in place (no directory entry removed and made again:\n"
         "        // 290 ms for a save on the PS5's USB drive, mgr_025 17:02:30), or by delete +\n"
         "        // recreate where the entry can't be truncated (ci/patch_framework.py overwrite_in_place).\n"
         "        if (entry->Truncate()) {\n"
         "        } else if (entry->Delete()) {\n"
         "          entry = nullptr;\n"
         "        } else {\n"
         "          return X_STATUS_ACCESS_DENIED;\n"
         "        }\n")


def wait_diag(sdk):
    """Who ends a long wait of the game's main thread (log only: nothing the game does changes).

    Every in-play dip under 60 in mgr_013..023 is one 280-360 ms stop where the main thread waits
    on a semaphore from the CRT wait wrapper (sub_82325630, "from game code 82325668"), the GPU
    idle, then a burst of reads. That site says nothing about which wait it is. The "ps5 hitch"
    line now also gives the waiter's callers (three return addresses up the guest back chain:
    lr at back_chain - 8, as the title's savegprlr prologues store it) and, for a semaphore, the
    thread that released it last, when, and its callers. Semaphore releases record that in a
    64-entry table (four relaxed atomic stores a release).
    """
    diag = sdk / "include" / "rex" / "ps5_diag.h"
    edit(diag,
         "}  // namespace rex::ps5diag",
         "// [mgr wait diag] the last release of a semaphore, by handle (64 slots, newest wins)\n"
         "struct ReleaseNote {\n"
         "  std::atomic<uint32_t> handle{0}, thread{0}, lr[3]{};\n"
         "  std::atomic<uint64_t> ms{0};\n"
         "};\n"
         "inline ReleaseNote g_release_notes[64];\n"
         "inline ReleaseNote& ReleaseNoteFor(uint32_t handle) { return g_release_notes[(handle >> 2) & 63]; }\n"
         "// (return addresses up a guest back chain: lr at back_chain - 8; 0 past the stack's ends;\n"
         "// read: a function giving the big-endian word at a guest address)\n"
         "template <typename Read>\n"
         "inline void GuestCallers(Read read, uint32_t sp, uint32_t lo, uint32_t hi, uint32_t* out, int n) {\n"
         "  for (int i = 0; i < n; ++i) {\n"
         "    out[i] = 0;\n"
         "    if (!sp || sp < lo || sp >= hi) continue;\n"
         "    const uint32_t back = read(sp);\n"
         "    if (back <= sp || back < lo || back > hi) { sp = 0; continue; }\n"
         "    out[i] = read(back - 8);\n"
         "    sp = back;\n"
         "  }\n"
         "}\n"
         "}  // namespace rex::ps5diag")
    sem = sdk / "src" / "system" / "xsemaphore.cpp"
    edit(sem,
         "#include <rex/system/xsemaphore.h>\n",
         "#include <rex/system/xsemaphore.h>\n"
         "#if REX_PLATFORM_PS5\n"
         "#include <rex/memory/utils.h>\n"
         "#include <rex/ps5_diag.h>\n"
         "#include <rex/system/kernel_state.h>\n"
         "#include <rex/system/thread_state.h>\n"
         "#include <rex/system/xthread.h>\n"
         "#endif\n")
    edit(sem,
         "  bool success = semaphore_->Release(release_count, &previous_count);\n",
         "#if REX_PLATFORM_PS5\n"
         "  // [mgr wait diag] who released it, for the main thread's \"ps5 hitch\" line (log only)\n"
         "  if (auto* t = XThread::GetCurrentThread(); t && t->thread_state() && t->thread_state()->context()) {\n"
         "    auto* ctx = t->thread_state()->context();\n"
         "    auto* mem = memory();\n"
         "    uint32_t up[2];\n"
         "    rex::ps5diag::GuestCallers(\n"
         "        [mem](uint32_t a) { return rex::memory::load_and_swap<uint32_t>(mem->TranslateVirtual<uint8_t*>(a)); },\n"
         "        uint32_t(ctx->r1.u32), t->guest_stack_limit(), t->guest_stack_base(), up, 2);\n"
         "    auto& note = rex::ps5diag::ReleaseNoteFor(handle());\n"
         "    note.handle.store(handle(), std::memory_order_relaxed);\n"
         "    note.thread.store(t->handle(), std::memory_order_relaxed);\n"
         "    note.lr[0].store(uint32_t(ctx->lr), std::memory_order_relaxed);\n"
         "    note.lr[1].store(up[0], std::memory_order_relaxed);\n"
         "    note.lr[2].store(up[1], std::memory_order_relaxed);\n"
         "    note.ms.store(rex::ps5diag::NowMs(), std::memory_order_relaxed);\n"
         "  }\n"
         "#endif\n"
         "  bool success = semaphore_->Release(release_count, &previous_count);\n")
    xo = sdk / "src" / "system" / "xobject.cpp"
    edit(xo,
         "#include <rex/ps5_diag.h>\n#include <rex/system/thread_state.h>\n#endif\n",
         "#include <rex/ps5_diag.h>\n#include <rex/system/thread_state.h>\n#include <rex/memory/utils.h>\n#endif\n")
    edit(xo,
         "struct Ps5WaitScope {\n  rex::ps5diag::WaitSlot* slot;\n",
         "struct Ps5WaitScope {\n  rex::ps5diag::WaitSlot* slot;\n"
         "  rex::memory::Memory* mem = nullptr;  // [mgr wait diag]\n")
    edit(xo,
         "    slot->object_type = first ? uint32_t(first->type()) : 0;\n",
         "    mem = first ? first->memory() : nullptr;\n"
         "    slot->object_type = first ? uint32_t(first->type()) : 0;\n")
    edit(xo,
         "    REXLOG_INFO(\"ps5 hitch: the game's main thread waited {} ms on {} {} handle {:08X} from game \"\n"
         "                \"code {:08X}{}\",\n",
         "    // [mgr wait diag] the waiter's callers, and who released the semaphore\n"
         "    std::string who;\n"
         "    if (mem) {\n"
         "      auto read = [this](uint32_t a) {\n"
         "        return rex::memory::load_and_swap<uint32_t>(mem->TranslateVirtual<uint8_t*>(a));\n"
         "      };\n"
         "      uint32_t up[3];\n"
         "      rex::ps5diag::GuestCallers(read, slot->guest_sp, slot->guest_stack_lo, slot->guest_stack_hi, up, 3);\n"
         "      who = fmt::format(\"; called from {:08X} < {:08X} < {:08X}\", up[0], up[1], up[2]);\n"
         "      auto& note = rex::ps5diag::ReleaseNoteFor(slot->handle);\n"
         "      const uint64_t at = note.ms.load(std::memory_order_relaxed);\n"
         "      if (slot->object_type == uint32_t(rex::system::XObject::Type::Semaphore) &&\n"
         "          note.handle.load(std::memory_order_relaxed) == slot->handle && at >= since) {\n"
         "        who += fmt::format(\"; released by thread {:08X} {} ms in, from {:08X} < {:08X} < {:08X}\",\n"
         "                           note.thread.load(std::memory_order_relaxed), at - since,\n"
         "                           note.lr[0].load(std::memory_order_relaxed),\n"
         "                           note.lr[1].load(std::memory_order_relaxed),\n"
         "                           note.lr[2].load(std::memory_order_relaxed));\n"
         "      }\n"
         "    }\n"
         "    REXLOG_INFO(\"ps5 hitch: the game's main thread waited {} ms on {} {} handle {:08X} from game \"\n"
         "                \"code {:08X}{}{}\",\n")
    edit(xo,
         "                    : std::string());\n  }\n};\n#else",
         "                    : std::string(),\n                who);\n  }\n};\n#else")


def draw_profile(sdk):
    """What one draw costs on the GPU command thread (cvar gpu_draw_profile, rex/<port>_perf.h).

    IssueDraw is timed step by step with the CPU's tick counter (each step exclusive: primitives,
    shaders and samplers, texture requests, render targets, pipeline, layout + viewport + dynamic
    state, system constants, bindings, vertex buffers, barriers + render pass, recording, the rest),
    and every 10 s the "draw cost" line gives each step per frame and per draw, plus the GPU
    thread's busy time outside IssueDraw (PM4 packets and register writes). Timing only: nothing
    the GPU draws changes. Self-contained, for any port with a <port>_perf.h of this shape.
    """
    vcp = sdk / "src" / "graphics" / "vulkan" / "command_processor.cpp"
    edit(vcp,
         "REXCVAR_DEFINE_BOOL(vulkan_readback_resolve, false, \"GPU/Vulkan\",\n",
         "REXCVAR_DEFINE_BOOL(gpu_draw_profile, false, \"GPU\",\n"
         "                    \"Time each step of a draw on the GPU command thread (the 'draw cost' log line, \"\n"
         "                    \"every 10 s)\");\n"
         "REXCVAR_DEFINE_BOOL(vulkan_readback_resolve, false, \"GPU/Vulkan\",\n")
    P = "rex::mgr_perf::"
    steps = [
        ("  memexport_ranges_.clear();\n\n  // Vertex shader analysis.\n",
         f"  {P}DrawPhases mgr_dp(REXCVAR_GET(gpu_draw_profile));  // [perf] the draw profile\n", None),
        ("    // Process primitives.\n    if (!primitive_processor_->Process(primitive_processing_result)) {",
         None, "kPrimitive"),
        ("    // Shader modifications.\n    vertex_shader_modification", None, "kDrawShaders"),
        ("  uint32_t normalized_color_mask =\n      pixel_shader ? draw_util::GetNormalizedColorMask",
         None, "kDrawSetup"),
        ("  texture_cache_->RequestTextures(used_texture_mask);", None, "kTexRequest"),
        ("  // Set up the render targets - this may perform dispatches and draws.", None, "kRtUpdate"),
        ("  // Create the pipeline (for this, need the render pass from the render target", None, "kPipeline"),
        ("  bool host_render_targets_used =\n      render_target_cache_->GetPath()", None, "kDynState"),
        ("  // Update system constants before uploading them.", None, "kSysConst"),
        ("  // Update uniform buffers and descriptor sets after binding the pipeline with", None, "kBindings"),
        ("  // Ensure vertex buffers are resident.", None, "kVertexFetch"),
        ("  // Synchronize the memory pages backing memory scatter export streams, and", None, "kRenderPass"),
        ("  // Draw.\n  ++frame_flow_draw_submitted_;", None, "kRecord"),
    ]
    for anchor, after, phase in steps:
        if after:  # (placed after the anchor)
            edit(vcp, anchor, anchor.split("\n\n")[0] + "\n" + after + "\n" + anchor.split("\n\n", 1)[1])
        else:  # (the step starts here)
            edit(vcp, anchor, f"  mgr_dp.To({P}{phase});  // [perf]\n" + anchor)
    edit(vcp,
         "                  n[kReadbackLate], ms[kOcclusion], n[kOcclusion]);\n",
         "                  n[kReadbackLate], ms[kOcclusion], n[kOcclusion]);\n"
         "      if (REXCVAR_GET(gpu_draw_profile)) {\n"
         "        // [perf] the draw profile: each step's ticks in ms a frame (ticks per ns from the clock)\n"
         "        static uint64_t prev_tk[kCount], prev_ticks = 0, prev_clock = 0;\n"
         "        const uint64_t ticks = Ticks(), clock = NowNs();\n"
         "        if (prev_ticks && clock > prev_clock && ticks > prev_ticks) {\n"
         "          const double tk_per_ms = double(ticks - prev_ticks) / (double(clock - prev_clock) / 1e6);\n"
         "          double st[kCount], sum = 0;\n"
         "          for (uint32_t c = 0; c < kCount; ++c) {\n"
         "            const uint64_t v = g_tk[c].load(std::memory_order_relaxed);\n"
         "            st[c] = double(v - prev_tk[c]) / tk_per_ms / double(frames);\n"
         "            sum += st[c];\n"
         "          }\n"
         "          const double busy = std::max(0.0, frame_ms - ms[kIdle] - ms[kWaitRegMem] - ms[kFenceWait] -\n"
         "                                                 ms[kSubmit] - ms[kSwap] - ms[kCopy] - ms[kOcclusion]);\n"
         "          const double per = n[kDraw] > 0 ? 1000.0 / n[kDraw] : 0;  // (ms a frame -> us a draw)\n"
         "          // (the profile's own cost: 13 tick reads and adds a draw, measured here)\n"
         "          static double own_us = -1;\n"
         "          if (own_us < 0) {\n"
         "            const uint64_t keep0 = g_tk[kDrawSetup].load(), keep1 = g_tk[kDrawShaders].load();\n"
         "            const uint64_t t0 = Ticks();\n"
         "            {\n"
         "              DrawPhases probe(true);\n"
         "              for (int i = 0; i < 1300; ++i) probe.To(Counter(kDrawSetup + (i & 1)));\n"
         "            }\n"
         "            own_us = double(Ticks() - t0) / tk_per_ms * 1000.0 / 100.0;  // (100 draws' worth)\n"
         "            g_tk[kDrawSetup].store(keep0);\n"
         "            g_tk[kDrawShaders].store(keep1);\n"
         "          }\n"
         "          REXGPU_INFO(\"draw cost: {:.0f} draws a frame, IssueDraw {:.2f} ms ({:.2f} us a draw): primitives {:.2f}, \"\n"
         "                      \"shaders+samplers {:.2f}, texture requests {:.2f}, render targets {:.2f}, pipeline {:.2f}, \"\n"
         "                      \"layout+viewport+dynamic {:.2f}, system constants {:.2f}, bindings {:.2f}, \"\n"
         "                      \"vertex buffers {:.2f}, barriers+render pass {:.2f}, record {:.2f}, the rest {:.2f} \"\n"
         "                      \"(us a draw: {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f}); \"\n"
         "                      \"GPU thread busy outside draws {:.2f} ms (PM4 packets, register writes); the profile's own cost {:.2f} us a draw\",\n"
         "                      n[kDraw], sum, sum * per, st[kPrimitive], st[kDrawShaders], st[kTexRequest], st[kRtUpdate],\n"
         "                      st[kPipeline], st[kDynState], st[kSysConst], st[kBindings], st[kVertexFetch],\n"
         "                      st[kRenderPass], st[kRecord], st[kDrawSetup], st[kPrimitive] * per,\n"
         "                      st[kDrawShaders] * per, st[kTexRequest] * per, st[kRtUpdate] * per, st[kPipeline] * per,\n"
         "                      st[kDynState] * per, st[kSysConst] * per, st[kBindings] * per, st[kVertexFetch] * per,\n"
         "                      st[kRenderPass] * per, st[kRecord] * per, st[kDrawSetup] * per,\n"
         "                      std::max(0.0, busy - sum), own_us);\n"
         "        }\n"
         "        for (uint32_t c = 0; c < kCount; ++c) prev_tk[c] = g_tk[c].load(std::memory_order_relaxed);\n"
         "        prev_ticks = ticks;\n"
         "        prev_clock = clock;\n"
         "      }\n")


if __name__ == "__main__":
    main()
