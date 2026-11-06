/**
 * Where the GPU thread's time goes, for the Metal Gear Rising: Revengeance PS5 log (patched in
 * by ci/patch_framework.py). Each counter is nanoseconds (and a count) on the
 * GPU command processor thread; IssueSwap prints them per frame every 10 s as
 * "mgr perf".
 */
#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>

namespace rex::mgr_perf {

enum Counter : uint32_t {
  kIdle,          // ring buffer empty: waiting for the game to submit
  kWaitRegMem,    // PM4 WAIT_REG_MEM sleeps (the command stream waiting on memory)
  kFenceWait,     // blocking on GPU fences (the GPU is behind)
  kSubmit,        // EndSubmission (recording replay + vkQueueSubmit)
  kSwap,          // IssueSwap (output to the presenter)
  kTextureLoad,   // texture uploads from guest memory (includes kHd)
  kHd,            // HD textures: hashing and uploads
  kPipeline,      // ConfigurePipeline (shader translation, pipeline creation)
  kDraw,          // IssueDraw in total (includes kTextureLoad and kPipeline)
  kCopy,          // IssueCopy (resolves)
  kReadbackLate,  // (count only) resolve readbacks not written by the GPU yet
  kOcclusion,     // EndGuestOcclusionQuery (awaits the GPU)
  kPrimitive,     // in draws: primitive processing (index buffers)
  kTexRequest,    // in draws: RequestTextures (includes kTextureLoad)
  kRtUpdate,      // in draws: render target cache update
  kSysConst,      // in draws: system constants
  kBindings,      // in draws: UpdateBindings (constants, descriptors)
  kVertexFetch,   // in draws: vertex buffer requests
  kRenderPass,    // in draws: barriers and entering the render pass
  kDrawSetup,     // in draws: shader analysis, counters, the rest of IssueDraw's own code
  kDrawShaders,   // in draws: submission, shader modifications and translations, samplers
  kDynState,      // in draws: pipeline layout, viewport and dynamic state
  kRecord,        // in draws: index buffer bind and the draw recorded
  kConstWrite,    // (count only) shader / fetch / bool / loop constant register writes
  kConstSkip,     // (count only) ... of them, every value already there: nothing invalidated
  kCount
};

// gpu_skip_unchanged_writes 2 (alternate): whether the skip is on in this 10 s window (the GPU
// thread's report flips it).
inline bool g_skip_window_on = true;

inline std::atomic<uint64_t> g_ns[kCount];
inline std::atomic<uint64_t> g_n[kCount];

// (a count from the GPU thread only: no locked instruction)
inline void CountOnGpuThread(Counter c) {
  g_n[c].store(g_n[c].load(std::memory_order_relaxed) + 1, std::memory_order_relaxed);
}

// The draw profile (gpu_draw_profile): IssueDraw's time by step, in CPU ticks (rdtsc: a few ns
// to read, where the steady clock can be a system call), each step exclusive. The 10 s report
// turns ticks into time against the steady clock.
inline std::atomic<uint64_t> g_tk[kCount];
inline uint64_t Ticks() {
#if defined(__x86_64__)
  return __builtin_ia32_rdtsc();
#else
  return uint64_t(std::chrono::steady_clock::now().time_since_epoch().count());
#endif
}
struct DrawPhases {
  Counter c = kDrawSetup;
  uint64_t t = 0;
  bool on;
  explicit DrawPhases(bool enabled) : on(enabled) {
    if (on) t = Ticks();
  }
  // (charges the time since the last step to it, and starts the next; IssueDraw runs on the GPU
  // thread only, so a plain add, no locked instruction: a tick read and an add a step)
  void To(Counter next) {
    if (!on) return;
    const uint64_t now = Ticks();
    g_tk[c].store(g_tk[c].load(std::memory_order_relaxed) + (now - t), std::memory_order_relaxed);
    c = next;
    t = now;
  }
  ~DrawPhases() { To(kDrawSetup); }
};

inline uint64_t NowUs() {
  return uint64_t(std::chrono::duration_cast<std::chrono::microseconds>(
                      std::chrono::steady_clock::now().time_since_epoch())
                      .count());
}

inline uint64_t NowNs() {
  return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                      std::chrono::steady_clock::now().time_since_epoch())
                      .count());
}

struct Scope {
  Counter c;
  uint64_t start;
  bool on = true;
  explicit Scope(Counter c) : c(c), start(NowNs()) {}
  void Stop() {
    if (!on) return;
    on = false;
    g_ns[c].fetch_add(NowNs() - start, std::memory_order_relaxed);
    g_n[c].fetch_add(1, std::memory_order_relaxed);
  }
  // (ends this one and starts timing the next step)
  void Next(Counter next) {
    Stop();
    c = next;
    start = NowNs();
    on = true;
  }
  ~Scope() { Stop(); }
};

template <typename F>
inline auto Timed(Counter c, F&& f) {
  Scope s(c);
  return f();
}

}  // namespace rex::mgr_perf
