/* Metal Gear Rising: Revengeance RePlatinum - a zip archive's files read out, for the HD cutscenes' packs.
 *
 * The PC version's 60 fps cutscene packs (Nexus Mods, Metal Gear Rising: Revengeance mod 505: "All
 * Cutscenes pt1" and "pt2") are zip files of 15 and 7 GB, their movies compressed with Deflate64 (zip
 * method 9: Deflate with a 64 KB window, length code 285 carrying 16 extra bits and distance codes 30
 * and 31). This reads a zip's central directory (Zip64 too) and inflates an entry - stored, Deflate or
 * Deflate64 - checking its CRC-32 and size.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace recomp::unzip
{
struct Entry
{
    std::string name;
    std::uint16_t method = 0; /* 0 stored, 8 Deflate, 9 Deflate64 */
    std::uint32_t crc = 0;
    std::uint64_t size = 0, packed = 0, header = 0; /* (header: its local header's offset) */
};

class Archive
{
  public:
    ~Archive();
    bool open(const std::string &path, std::string &error);
    void close();
    const std::vector<Entry> &entries() const { return entries_; }
    /* The entry's data, a piece at a time, to `sink` (false from it: stop). False with `error` when
     * the data is damaged, can't be read or (`sink` aside) stopped. */
    bool read(const Entry &e, const std::function<bool(const std::uint8_t *, std::size_t)> &sink,
              std::string &error);

  private:
    bool pread_all(std::uint64_t off, void *buf, std::size_t n);
    int fd_ = -1;
    std::uint64_t file_size_ = 0;
    std::vector<Entry> entries_;
};
} // namespace recomp::unzip
