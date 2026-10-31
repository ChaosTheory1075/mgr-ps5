/* Metal Gear Rising: Revengeance RePlatinum - see store_unzip.hpp.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include "store_unzip.hpp"

#include <algorithm>
#include <cstring>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace recomp::unzip
{
namespace
{
std::uint16_t le16(const std::uint8_t *p) { return std::uint16_t(p[0] | p[1] << 8); }
std::uint32_t le32(const std::uint8_t *p) { return std::uint32_t(p[0]) | std::uint32_t(p[1]) << 8 | std::uint32_t(p[2]) << 16 | std::uint32_t(p[3]) << 24; }
std::uint64_t le64(const std::uint8_t *p) { return std::uint64_t(le32(p)) | std::uint64_t(le32(p + 4)) << 32; }

struct Crc
{
    std::uint32_t table[8][256];
    Crc()
    {
        for (std::uint32_t i = 0; i < 256; ++i)
        {
            std::uint32_t c = i;
            for (int k = 0; k < 8; ++k)
                c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[0][i] = c;
        }
        for (std::uint32_t i = 0; i < 256; ++i)
            for (int t = 1; t < 8; ++t)
                table[t][i] = (table[t - 1][i] >> 8) ^ table[0][table[t - 1][i] & 0xFF];
    }
    std::uint32_t update(std::uint32_t crc, const std::uint8_t *p, std::size_t n) const
    {
        crc = ~crc;
        while (n >= 8)
        {
            const std::uint32_t a = crc ^ le32(p), b = le32(p + 4);
            crc = table[7][a & 0xFF] ^ table[6][(a >> 8) & 0xFF] ^ table[5][(a >> 16) & 0xFF] ^ table[4][a >> 24] ^
                  table[3][b & 0xFF] ^ table[2][(b >> 8) & 0xFF] ^ table[1][(b >> 16) & 0xFF] ^ table[0][b >> 24];
            p += 8;
            n -= 8;
        }
        while (n--)
            crc = table[0][(crc ^ *p++) & 0xFF] ^ (crc >> 8);
        return ~crc;
    }
};
const Crc &crc_table()
{
    static const Crc crc;
    return crc;
}

/* The compressed data, read in big pieces, as bits (least significant first). */
class Bits
{
  public:
    Bits(int fd, std::uint64_t off, std::uint64_t size) : fd_(fd), off_(off), left_(size), buf_(4u << 20) {}
    /* (past the data's end: zeros, counted - more than a few is damage) */
    bool need(int n)
    {
        while (nb_ < n)
        {
            if (at_ == end_ && !fill())
            {
                if (++overrun_ > 8)
                    return false;
                nb_ += 8;
                continue;
            }
            bb_ |= std::uint64_t(buf_[at_++]) << nb_;
            nb_ += 8;
        }
        return true;
    }
    std::uint32_t peek(int n) const { return std::uint32_t(bb_ & ((std::uint64_t(1) << n) - 1)); }
    void drop(int n)
    {
        bb_ >>= n;
        nb_ -= n;
    }
    bool get(int n, std::uint32_t &v)
    {
        if (!n)
        {
            v = 0;
            return true;
        }
        if (!need(n))
            return false;
        v = peek(n);
        drop(n);
        return true;
    }
    void align() { drop(nb_ & 7); }
    bool failed() const { return read_failed_; }

  private:
    bool fill()
    {
        if (!left_)
            return false;
        const std::size_t want = std::size_t(std::min<std::uint64_t>(left_, buf_.size()));
        std::size_t got = 0;
        while (got < want)
        {
            const ssize_t r = ::pread(fd_, buf_.data() + got, want - got, off_t(off_ + got));
            if (r <= 0)
            {
                read_failed_ = true;
                return false;
            }
            got += std::size_t(r);
        }
        off_ += want;
        left_ -= want;
        at_ = 0;
        end_ = want;
        return true;
    }
    int fd_;
    std::uint64_t off_, left_;
    std::vector<std::uint8_t> buf_;
    std::size_t at_ = 0, end_ = 0;
    std::uint64_t bb_ = 0;
    int nb_ = 0, overrun_ = 0;
    bool read_failed_ = false;
};

/* A Huffman code as a table of every `bits`-bit pattern: (symbol << 4) | its code's length (0: no code). */
struct Code
{
    std::vector<std::uint16_t> table;
    int bits = 0;
    bool build(const std::uint8_t *lengths, int count)
    {
        int bl_count[16] = {};
        bits = 0;
        for (int i = 0; i < count; ++i)
        {
            bl_count[lengths[i]]++;
            bits = std::max(bits, int(lengths[i]));
        }
        table.assign(std::size_t(1) << bits, 0);
        if (!bits)
            return true;
        bl_count[0] = 0;
        int next[16] = {}, code = 0, left = 1;
        for (int len = 1; len <= 15; ++len)
        {
            left = (left << 1) - bl_count[len];
            if (left < 0)
                return false; /* (over-subscribed) */
            code = (code + bl_count[len - 1]) << 1;
            next[len] = code;
        }
        for (int sym = 0; sym < count; ++sym)
        {
            const int len = lengths[sym];
            if (!len)
                continue;
            int c = next[len]++, rev = 0;
            for (int k = 0; k < len; ++k, c >>= 1)
                rev = (rev << 1) | (c & 1);
            for (int i = rev; i < (1 << bits); i += 1 << len)
                table[std::size_t(i)] = std::uint16_t(sym << 4 | len);
        }
        return true;
    }
    /* the next symbol, or -1 */
    int decode(Bits &in) const
    {
        if (!bits || !in.need(bits))
            return -1;
        const std::uint16_t t = table[in.peek(bits)];
        if (!(t & 15))
            return -1;
        in.drop(t & 15);
        return t >> 4;
    }
};

const std::uint16_t kLengthBase[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27,
                                       31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
const std::uint8_t kLengthExtra[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
const std::uint32_t kDistBase[32] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
                                     257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
                                     32769, 49153};
const std::uint8_t kDistExtra[32] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
                                     7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14};

/* The output: the last 64 KB kept for matches, the rest handed on in big pieces. */
class Out
{
  public:
    static constexpr std::size_t kHistory = 65536, kChunk = 8u << 20;
    Out(const std::function<bool(const std::uint8_t *, std::size_t)> &sink) : sink_(sink), buf_(kHistory + kChunk + 70000) {}
    /* room for a match's whole length (Deflate64's longest: 65538) */
    bool room()
    {
        if (p_ < kHistory + kChunk)
            return true;
        return flush();
    }
    void byte(std::uint8_t b) { buf_[p_++] = b; }
    bool copy(std::uint32_t dist, std::uint32_t len)
    {
        if (dist > total_ + (p_ - from_) || dist > kHistory)
            return false;
        std::uint8_t *d = buf_.data() + p_;
        const std::uint8_t *s = d - dist;
        if (dist >= len)
            std::memcpy(d, s, len);
        else
            for (std::uint32_t i = 0; i < len; ++i)
                d[i] = s[i];
        p_ += len;
        return true;
    }
    bool flush()
    {
        if (p_ > from_)
        {
            crc_ = crc_table().update(crc_, buf_.data() + from_, p_ - from_);
            total_ += p_ - from_;
            if (!sink_(buf_.data() + from_, p_ - from_))
            {
                stopped_ = true;
                return false;
            }
        }
        if (p_ > kHistory)
        {
            std::memmove(buf_.data(), buf_.data() + p_ - kHistory, kHistory);
            p_ = kHistory;
        }
        from_ = p_;
        return true;
    }
    std::uint64_t total() const { return total_; }
    std::uint32_t crc() const { return crc_; }
    bool stopped() const { return stopped_; }

  private:
    const std::function<bool(const std::uint8_t *, std::size_t)> &sink_;
    std::vector<std::uint8_t> buf_;
    std::size_t p_ = 0, from_ = 0;
    std::uint64_t total_ = 0;
    std::uint32_t crc_ = 0;
    bool stopped_ = false;
};

/* Deflate (or, `d64`, Deflate64) from `in` to `out`. */
bool inflate(Bits &in, Out &out, bool d64, std::string &error)
{
    Code lit, dist;
    std::uint32_t last = 0;
    while (!last)
    {
        std::uint32_t type;
        if (!in.get(1, last) || !in.get(2, type))
            break;
        if (type == 0)
        {
            in.align();
            std::uint32_t len, nlen;
            if (!in.get(16, len) || !in.get(16, nlen) || (len ^ 0xFFFF) != nlen)
            {
                error = "a stored block is damaged";
                return false;
            }
            while (len--)
            {
                std::uint32_t b;
                if (!out.room() || !in.get(8, b))
                    goto ended;
                out.byte(std::uint8_t(b));
            }
            continue;
        }
        if (type == 1)
        {
            std::uint8_t l[288], d[32];
            std::memset(l, 8, 144);
            std::memset(l + 144, 9, 112);
            std::memset(l + 256, 7, 24);
            std::memset(l + 280, 8, 8);
            std::memset(d, 5, 32);
            lit.build(l, 288);
            dist.build(d, 32);
        }
        else if (type == 2)
        {
            std::uint32_t hlit, hdist, hclen;
            if (!in.get(5, hlit) || !in.get(5, hdist) || !in.get(4, hclen))
                break;
            hlit += 257, hdist += 1, hclen += 4;
            static const std::uint8_t order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
            std::uint8_t cl[19] = {};
            for (std::uint32_t i = 0; i < hclen; ++i)
            {
                std::uint32_t v;
                if (!in.get(3, v))
                    goto ended;
                cl[order[i]] = std::uint8_t(v);
            }
            Code lens;
            if (!lens.build(cl, 19))
            {
                error = "a block's code lengths are damaged";
                return false;
            }
            std::uint8_t l[320] = {};
            std::uint32_t n = 0;
            while (n < hlit + hdist)
            {
                const int sym = lens.decode(in);
                std::uint32_t rep = 0;
                std::uint8_t val = 0;
                if (sym < 0)
                {
                    error = "a block's code lengths are damaged";
                    return false;
                }
                if (sym < 16)
                {
                    l[n++] = std::uint8_t(sym);
                    continue;
                }
                if (sym == 16)
                {
                    if (!n || !in.get(2, rep))
                        goto damaged;
                    rep += 3, val = l[n - 1];
                }
                else if (sym == 17)
                {
                    if (!in.get(3, rep))
                        goto damaged;
                    rep += 3;
                }
                else
                {
                    if (!in.get(7, rep))
                        goto damaged;
                    rep += 11;
                }
                if (n + rep > hlit + hdist)
                    goto damaged;
                while (rep--)
                    l[n++] = val;
            }
            if (!lit.build(l, int(hlit)) || !dist.build(l + hlit, int(hdist)))
                goto damaged;
        }
        else
            goto damaged;
        for (;;)
        {
            if (!out.room())
                goto ended;
            const int sym = lit.decode(in);
            if (sym < 0)
                goto damaged;
            if (sym < 256)
            {
                out.byte(std::uint8_t(sym));
                continue;
            }
            if (sym == 256)
                break;
            const int li = sym - 257;
            if (li >= 29)
                goto damaged;
            std::uint32_t len, extra = (d64 && li == 28) ? 16 : kLengthExtra[li], e;
            if (!in.get(int(extra), e))
                goto damaged;
            len = ((d64 && li == 28) ? 3 : kLengthBase[li]) + e;
            const int ds = dist.decode(in);
            if (ds < 0 || ds >= (d64 ? 32 : 30))
                goto damaged;
            if (!in.get(kDistExtra[ds], e))
                goto damaged;
            if (!out.copy(kDistBase[ds] + e, len))
                goto damaged;
        }
    }
    if (!last)
        goto ended;
    return true;
ended:
    if (out.stopped())
        error = "stopped";
    else
        error = in.failed() ? "it couldn't be read" : "it ends early (the download may be incomplete)";
    return false;
damaged:
    error = in.failed() ? "it couldn't be read" : "its compressed data is damaged";
    return false;
}
} // namespace

Archive::~Archive() { close(); }

void Archive::close()
{
    if (fd_ >= 0)
        ::close(fd_);
    fd_ = -1;
    entries_.clear();
}

bool Archive::pread_all(std::uint64_t off, void *buf, std::size_t n)
{
    std::size_t got = 0;
    while (got < n)
    {
        const ssize_t r = ::pread(fd_, static_cast<std::uint8_t *>(buf) + got, n - got, off_t(off + got));
        if (r <= 0)
            return false;
        got += std::size_t(r);
    }
    return true;
}

bool Archive::open(const std::string &path, std::string &error)
{
    close();
    fd_ = ::open(path.c_str(), O_RDONLY);
    struct stat st;
    if (fd_ < 0 || fstat(fd_, &st) != 0)
    {
        error = "it couldn't be opened";
        return false;
    }
    file_size_ = std::uint64_t(st.st_size);
    /* the end of central directory record, in the last 64 KB (its comment) */
    const std::size_t tail = std::size_t(std::min<std::uint64_t>(file_size_, 65557));
    std::vector<std::uint8_t> t(tail);
    if (tail < 22 || !pread_all(file_size_ - tail, t.data(), tail))
    {
        error = "it isn't a zip file";
        return false;
    }
    std::size_t eocd = std::string::npos;
    for (std::size_t i = tail - 22 + 1; i-- > 0;)
        if (le32(&t[i]) == 0x06054b50)
        {
            eocd = i;
            break;
        }
    if (eocd == std::string::npos)
    {
        error = "it isn't a zip file (or it's incomplete)";
        return false;
    }
    std::uint64_t count = le16(&t[eocd + 10]), cd_size = le32(&t[eocd + 12]), cd_off = le32(&t[eocd + 16]);
    if (count == 0xFFFF || cd_size == 0xFFFFFFFF || cd_off == 0xFFFFFFFF)
    {
        /* Zip64: its locator just before, pointing at its own record */
        std::uint8_t loc[20], rec[56];
        const std::uint64_t at = file_size_ - tail + eocd;
        if (at < 20 || !pread_all(at - 20, loc, 20) || le32(loc) != 0x07064b50 || !pread_all(le64(loc + 8), rec, 56) ||
            le32(rec) != 0x06064b50)
        {
            error = "its Zip64 directory is damaged";
            return false;
        }
        count = le64(rec + 32), cd_size = le64(rec + 40), cd_off = le64(rec + 48);
    }
    if (cd_off + cd_size > file_size_ || cd_size > (256u << 20))
    {
        error = "its directory is damaged (or the file is incomplete)";
        return false;
    }
    std::vector<std::uint8_t> cd(static_cast<std::size_t>(cd_size));
    if (!pread_all(cd_off, cd.data(), cd.size()))
    {
        error = "its directory couldn't be read";
        return false;
    }
    std::size_t p = 0;
    for (std::uint64_t i = 0; i < count; ++i)
    {
        if (p + 46 > cd.size() || le32(&cd[p]) != 0x02014b50)
        {
            error = "its directory is damaged";
            return false;
        }
        Entry e;
        e.method = le16(&cd[p + 10]);
        e.crc = le32(&cd[p + 16]);
        e.packed = le32(&cd[p + 20]);
        e.size = le32(&cd[p + 24]);
        const std::size_t nl = le16(&cd[p + 28]), xl = le16(&cd[p + 30]), cl = le16(&cd[p + 32]);
        e.header = le32(&cd[p + 42]);
        if (p + 46 + nl + xl + cl > cd.size())
        {
            error = "its directory is damaged";
            return false;
        }
        e.name.assign(reinterpret_cast<const char *>(&cd[p + 46]), nl);
        /* Zip64's sizes and offset: in its extra field, those that didn't fit */
        for (std::size_t x = p + 46 + nl; x + 4 <= p + 46 + nl + xl;)
        {
            const std::uint16_t id = le16(&cd[x]), len = le16(&cd[x + 2]);
            if (x + 4 + len > p + 46 + nl + xl)
                break;
            if (id == 1)
            {
                std::size_t f = x + 4;
                const std::size_t end = f + len;
                if (e.size == 0xFFFFFFFF && f + 8 <= end)
                    e.size = le64(&cd[f]), f += 8;
                if (e.packed == 0xFFFFFFFF && f + 8 <= end)
                    e.packed = le64(&cd[f]), f += 8;
                if (e.header == 0xFFFFFFFF && f + 8 <= end)
                    e.header = le64(&cd[f]), f += 8;
            }
            x += 4 + len;
        }
        entries_.push_back(std::move(e));
        p += 46 + nl + xl + cl;
    }
    return true;
}

bool Archive::read(const Entry &e, const std::function<bool(const std::uint8_t *, std::size_t)> &sink, std::string &error)
{
    std::uint8_t lh[30];
    if (!pread_all(e.header, lh, 30) || le32(lh) != 0x04034b50)
    {
        error = "its entry " + e.name + " is damaged";
        return false;
    }
    const std::uint64_t data = e.header + 30 + le16(lh + 26) + le16(lh + 28);
    if (data + e.packed > file_size_)
    {
        error = e.name + " ends early (the download may be incomplete)";
        return false;
    }
    Out out(sink);
    std::string why;
    bool ok;
    if (e.method == 0)
    {
        std::vector<std::uint8_t> buf(8u << 20);
        ok = true;
        std::uint32_t crc = 0;
        for (std::uint64_t at = 0; ok && at < e.packed;)
        {
            const std::size_t n = std::size_t(std::min<std::uint64_t>(buf.size(), e.packed - at));
            if (!pread_all(data + at, buf.data(), n))
            {
                why = "it couldn't be read";
                ok = false;
                break;
            }
            crc = crc_table().update(crc, buf.data(), n);
            if (!sink(buf.data(), n))
            {
                why = "stopped";
                ok = false;
            }
            at += n;
        }
        if (ok && crc != e.crc)
        {
            error = e.name + " is damaged (its checksum doesn't match)";
            return false;
        }
        if (!ok)
            error = why == "stopped" ? why : e.name + ": " + why;
        return ok;
    }
    if (e.method != 8 && e.method != 9)
    {
        error = e.name + " is compressed in a way this can't read (method " + std::to_string(e.method) + ")";
        return false;
    }
    Bits in(fd_, data, e.packed);
    ok = inflate(in, out, e.method == 9, why) && out.flush();
    if (!ok)
    {
        error = out.stopped() || why == "stopped" ? std::string("stopped") : e.name + ": " + (why.empty() ? "it couldn't be written" : why);
        return false;
    }
    if (out.total() != e.size || out.crc() != e.crc)
    {
        error = e.name + " is damaged (its size or checksum doesn't match)";
        return false;
    }
    return true;
}
} // namespace recomp::unzip
