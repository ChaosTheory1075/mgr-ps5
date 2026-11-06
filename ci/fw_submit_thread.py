"""The submit thread, for any rex PS5 port (from Driver SF dsf-ps5 815c67e, 2026-11-05).

What it fixes: the GPU thread spends milliseconds of every frame in VulkanCommandProcessor::EndSubmission,
replaying the submission's recorded commands (DeferredCommandBuffer::Execute) into its Vulkan command buffer
(radv) and calling vkQueueSubmit - Driver SF 3-5.5 ms of a 17-22 ms frame in its dips, SR2 ~8.5 ms, Crackdown 2
11-12 ms ("submit" in the perf lines). With this, the replay and the submit run on a thread of their own (one
spare CPU, 5 by default) while the GPU thread goes on recording the next submission.

Why nothing changes on screen: the commands, their order and the queue order are the same. Anyone else who
acquires a Vulkan queue (the presenter, sparse binds, the lane...) first waits for the thread to be empty
(VulkanDevice::AcquireQueue's hook), and the GPU thread never waits on or polls a submission fence the thread
hasn't submitted yet (CheckSubmissionFenceAndDeviceLoss). A failed submit still signals the fence (an empty
submit), so no wait hangs on it. The cvar turns it off at start (read once, at the first submission).

How to use it, in a port's ci/patch_framework.py (after any edit of your own to the same lines):

    import fw_submit_thread
    fw_submit_thread.submit_thread(sdk, edit)                 # cvar gpu_submit_thread, CPU 5

  sdk   the rexglue-sdk-main folder; edit: your edit(path, old, new) (exits on a mismatch).
  Options: cvar="gpu_submit_thread", cpu=5 (a CPU your port leaves free: not the GPU thread's, not the lane's
  own, not the game's), default_on=True, perf_scope="rex::<port>_perf::Scope name(rex::<port>_perf::kSubmit);"
  to count the GPU thread's waits for the thread in your perf line's "submit" (optional).

It needs from the port: nothing but stock rex. It adds the includes it uses (<rex/frame_stats.h> for the
affinity, <rex/ps5_diag.h> for the thread's name) when they're missing. With the Crackdown lane (fw_perf_fixes:
"gpu lane" in ps5_diag.cpp's KeepOtherThreadsOn, GpuLane::Get().Drain() in ShutdownContext) it also keeps the
thread's CPU on beside the lane's and drains it at shutdown; without the lane those two steps are skipped (the
fence check already waits for everything at shutdown).

Log: "gpu submit thread: on (CPU N)" at start, then every 10 s "gpu submit thread: N submissions in 10.0 s,
X ms a second replaying and submitting; waited for N times, Y ms a second" (the second number is what the GPU
thread still waits; X - Y is about what it no longer spends).
"""

import pathlib


CLASS = r"""
// [submit thread] (ci/fw_submit_thread.py): a submission's recorded commands are replayed into its
// Vulkan command buffer and submitted here, in order, while the GPU thread records the next submission.
class SubmitThread {
 public:
  struct Job {
    std::vector<uintmax_t> stream;
    VkCommandBuffer command_buffer = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    std::vector<VkSemaphore> wait_semaphores;
    std::vector<VkPipelineStageFlags> wait_stage_masks;
    VkFence fence = VK_NULL_HANDLE;
    uint64_t submission = 0;
  };

  static SubmitThread& Get() {
    static SubmitThread thread;
    return thread;
  }

  // (from the GPU thread: the thread starts at the first submission)
  bool Active(VulkanCommandProcessor* command_processor) {
    if (state_ == kUnknown) {
      Start(command_processor);
    }
    return state_ == kRunning;
  }
  bool Running() const { return state_ == kRunning; }
  uint64_t Submitted() const { return submitted_.load(std::memory_order_acquire); }

  // An empty stream with room in it (one the thread is done with), or nothing.
  void TakeSpare(std::vector<uintmax_t>& stream) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!spares_.empty()) {
      stream = std::move(spares_.back());
      spares_.pop_back();
    }
  }

  void Push(Job&& job) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      jobs_.push_back(std::move(job));
    }
    work_cv_.notify_one();
  }

  // Until every submission up to `submission` is on the queue.
  void WaitSubmitted(uint64_t submission) {
    if (state_ != kRunning || Submitted() >= submission) {
      return;
    }
    std::unique_lock<std::mutex> lock(mutex_);
    const uint64_t start = NowUs();
    done_cv_.wait(lock, [&] {
      return submitted_.load(std::memory_order_acquire) >= submission || (jobs_.empty() && !busy_);
    });
    waited_us_ += NowUs() - start;
    ++waits_;
  }

  // Until the thread has submitted everything handed to it (not on the thread itself).
  void Drain() {
    if (state_ != kRunning || on_thread_) {
      return;
    }
    std::unique_lock<std::mutex> lock(mutex_);
    if (jobs_.empty() && !busy_) {
      return;
    }
    const uint64_t start = NowUs();
    done_cv_.wait(lock, [&] { return jobs_.empty() && !busy_; });
    waited_us_ += NowUs() - start;
    ++waits_;
  }

 private:
  enum State { kUnknown, kOff, kRunning };

  static uint64_t NowUs() {
    return uint64_t(std::chrono::duration_cast<std::chrono::microseconds>(
                        std::chrono::steady_clock::now().time_since_epoch())
                        .count());
  }

  void Start(VulkanCommandProcessor* command_processor) {
    command_processor_ = command_processor;
    state_ = REXCVAR_GET(@CVAR@) ? kRunning : kOff;
    REXGPU_INFO("gpu submit thread: {}", state_ == kRunning ? "on (CPU @CPU@)" : "off");
    if (state_ == kRunning) {
      ui::vulkan::g_before_queue_acquire = [] { SubmitThread::Get().Drain(); };
      std::thread([this] { Main(); }).detach();
    }
  }

  void Main() {
    on_thread_ = true;
#if defined(__PROSPERO__)
    rex::frame_stats::scePthreadSetaffinity(pthread_self(), uint64_t(1) << @CPU@);
#endif
    rex::ps5diag::RegisterThread("gpu submit");
    for (;;) {
      Job job;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        work_cv_.wait(lock, [&] { return !jobs_.empty(); });
        job = std::move(jobs_.front());
        jobs_.pop_front();
        busy_ = true;
      }
      const uint64_t start = NowUs();
      Run(job);
      const uint64_t end = NowUs();
      job.stream.clear();
      {
        std::lock_guard<std::mutex> lock(mutex_);
        busy_ = false;
        submitted_.store(job.submission, std::memory_order_release);
        busy_us_ += end - start;
        ++done_;
        if (spares_.size() < 8) {
          spares_.push_back(std::move(job.stream));
        }
      }
      done_cv_.notify_all();
      if (!report_us_) {
        report_us_ = end;
      } else if (end - report_us_ >= 10000000) {
        uint64_t busy_us, waited_us, waits, done;
        {
          std::lock_guard<std::mutex> lock(mutex_);
          busy_us = busy_us_;
          waited_us = waited_us_;
          waits = waits_;
          done = done_;
          busy_us_ = waited_us_ = waits_ = done_ = 0;
        }
        const double seconds = double(end - report_us_) / 1000000.0;
        report_us_ = end;
        REXGPU_INFO(
            "gpu submit thread: {} submissions in {:.1f} s, {:.1f} ms a second replaying and "
            "submitting; waited for {} times, {:.1f} ms a second",
            done, seconds, double(busy_us) / 1000.0 / seconds, waits, double(waited_us) / 1000.0 / seconds);
      }
    }
  }

  void Run(Job& job) {
    const ui::vulkan::VulkanDevice* const vulkan_device = command_processor_->GetVulkanDevice();
    const ui::vulkan::VulkanDevice::Functions& dfn = vulkan_device->functions();
    const VkDevice device = vulkan_device->device();
    bool recorded = dfn.vkResetCommandPool(device, job.pool, 0) == VK_SUCCESS;
    if (recorded) {
      VkCommandBufferBeginInfo begin_info = {};
      begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
      begin_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
      recorded = dfn.vkBeginCommandBuffer(job.command_buffer, &begin_info) == VK_SUCCESS;
    }
    if (recorded) {
      command_processor_->deferred_command_buffer().ExecuteStream(job.command_buffer, job.stream);
      recorded = dfn.vkEndCommandBuffer(job.command_buffer) == VK_SUCCESS;
    }
    if (!recorded) {
      REXGPU_ERROR("gpu submit thread: failed to record a Vulkan command buffer");
    }
    VkSubmitInfo submit_info = {};
    submit_info.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    if (!job.wait_semaphores.empty()) {
      submit_info.waitSemaphoreCount = uint32_t(job.wait_semaphores.size());
      submit_info.pWaitSemaphores = job.wait_semaphores.data();
      submit_info.pWaitDstStageMask = job.wait_stage_masks.data();
    }
    submit_info.commandBufferCount = recorded ? 1 : 0;
    submit_info.pCommandBuffers = &job.command_buffer;
    VkResult result;
    {
      ui::vulkan::VulkanDevice::Queue::Acquisition queue_acquisition =
          vulkan_device->AcquireQueue(vulkan_device->queue_family_graphics_compute(), 0);
      result = dfn.vkQueueSubmit(queue_acquisition.queue(), 1, &submit_info, job.fence);
      if (result != VK_SUCCESS && result != VK_ERROR_DEVICE_LOST) {
        // (the fence still signals: the GPU thread waits on it)
        VkSubmitInfo empty_submit = {};
        empty_submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        dfn.vkQueueSubmit(queue_acquisition.queue(), 1, &empty_submit, job.fence);
      }
    }
    if (result != VK_SUCCESS) {
      // (a lost device shows up at the GPU thread's next fence wait)
      REXGPU_ERROR("gpu submit thread: failed to submit a Vulkan command buffer ({})", int(result));
    }
  }

  static inline thread_local bool on_thread_ = false;
  State state_ = kUnknown;
  VulkanCommandProcessor* command_processor_ = nullptr;
  std::mutex mutex_;
  std::condition_variable work_cv_, done_cv_;
  std::deque<Job> jobs_;
  std::vector<std::vector<uintmax_t>> spares_;
  bool busy_ = false;
  std::atomic<uint64_t> submitted_{0};
  uint64_t busy_us_ = 0, waited_us_ = 0, waits_ = 0, done_ = 0, report_us_ = 0;
};
"""


def submit_thread(sdk, edit, cvar="gpu_submit_thread", cpu=5, default_on=True, perf_scope=None):
    sdk = pathlib.Path(sdk)

    # the queue hook: whoever acquires a queue first waits for the thread to be empty
    vk = sdk / "include" / "rex" / "ui" / "vulkan" / "device.h"
    edit(vk, "class VulkanDevice {\n",
         "// [submit thread] (called before a queue is acquired by a thread that doesn't hold one already)\n"
         "inline void (*g_before_queue_acquire)() = nullptr;\n"
         "inline thread_local int g_queue_acquisitions = 0;\n\n"
         "class VulkanDevice {\n")
    edit(vk, "      explicit Acquisition(Queue& queue) : lock_(queue.mutex), queue_(queue.queue) {}\n",
         "      explicit Acquisition(Queue& queue) : lock_(queue.mutex), queue_(queue.queue) {\n"
         "        ++g_queue_acquisitions;  // [submit thread]\n"
         "      }\n"
         "      Acquisition(Acquisition&& other) = default;\n"
         "      ~Acquisition() {\n"
         "        if (lock_.owns_lock()) {\n"
         "          --g_queue_acquisitions;\n"
         "        }\n"
         "      }\n")
    edit(vk, "                                  const uint32_t queue_index) const {\n"
             "    return queue_families()[queue_family_index].queues[queue_index]->Acquire();\n",
         "                                  const uint32_t queue_index) const {\n"
         "    if (g_before_queue_acquire && !g_queue_acquisitions) {\n"
         "      g_before_queue_acquire();  // [submit thread] its submissions go first\n"
         "    }\n"
         "    return queue_families()[queue_family_index].queues[queue_index]->Acquire();\n")

    # the recorded commands handed over, and replayed from a stream of their own
    dcb_h = sdk / "include" / "rex" / "graphics" / "vulkan" / "deferred_command_buffer.h"
    edit(dcb_h, "  void Execute(VkCommandBuffer command_buffer);\n",
         "  void Execute(VkCommandBuffer command_buffer);\n"
         "  // [submit thread] (the recorded commands handed over, an empty stream in their place; and\n"
         "  // replayed from there)\n"
         "  void TakeStream(std::vector<uintmax_t>& stream) {\n"
         "    stream.swap(command_stream_);\n"
         "    command_stream_.clear();\n"
         "  }\n"
         "  void ExecuteStream(VkCommandBuffer command_buffer, const std::vector<uintmax_t>& commands);\n")
    dcb = sdk / "src" / "graphics" / "vulkan" / "deferred_command_buffer.cpp"
    edit(dcb, "void DeferredCommandBuffer::Execute(VkCommandBuffer command_buffer) {\n",
         "void DeferredCommandBuffer::Execute(VkCommandBuffer command_buffer) {\n"
         "  ExecuteStream(command_buffer, command_stream_);\n"
         "}\n\n"
         "void DeferredCommandBuffer::ExecuteStream(VkCommandBuffer command_buffer,\n"
         "                                          const std::vector<uintmax_t>& commands) {\n")
    edit(dcb, "  const uintmax_t* stream = command_stream_.data();\n"
              "  size_t stream_remaining = command_stream_.size();\n",
         "  const uintmax_t* stream = commands.data();  // [submit thread]\n"
         "  size_t stream_remaining = commands.size();\n")

    # (the Crackdown lane's diag: the thread's CPU kept on beside the lane's)
    diag = sdk / "src" / "core" / "ps5_diag.cpp"
    if '!std::strcmp(e.what, "gpu lane"))\n' in diag.read_text():
        edit(diag, '!std::strcmp(e.what, "gpu lane"))\n',
             '!std::strcmp(e.what, "gpu lane") ||\n'
             '        !std::strcmp(e.what, "gpu submit"))  // [submit thread]\n')

    cp = sdk / "src" / "graphics" / "vulkan" / "command_processor.cpp"
    text = cp.read_text()
    edit(cp, "#include <mutex>\n",
         "#include <mutex>\n#include <chrono>  // [submit thread]\n#include <condition_variable>\n#include <deque>\n"
         "#include <thread>\n")
    for header in ("<rex/frame_stats.h>", "<rex/ps5_diag.h>"):
        if "#include " + header not in text:
            edit(cp, "#include <rex/cvar.h>\n", "#include <rex/cvar.h>\n#include " + header + "  // [submit thread]\n")
    edit(cp, 'REXCVAR_DEFINE_BOOL(vulkan_dynamic_rendering, true, "GPU/Vulkan",\n',
         'REXCVAR_DEFINE_BOOL(' + cvar + ', ' + ("true" if default_on else "false") + ', "GPU/Vulkan",\n'
         '                    "Replay and submit each submission\'s Vulkan commands on a thread of its own "\n'
         '                    "(CPU ' + str(cpu) + ') while the GPU thread goes on with the next draws");\n\n'
         'REXCVAR_DEFINE_BOOL(vulkan_dynamic_rendering, true, "GPU/Vulkan",\n')
    edit(cp, "namespace rex::graphics::vulkan {\n",
         "namespace rex::graphics::vulkan {\n" + CLASS.replace("@CVAR@", cvar).replace("@CPU@", str(cpu)))
    # (at shutdown, with the lane: its drain, then the thread's)
    if "  GpuLane::Get().Drain();  // [crackdown]\n  AwaitAllQueueOperationsCompletion();\n" in text:
        edit(cp, "  GpuLane::Get().Drain();  // [crackdown]\n  AwaitAllQueueOperationsCompletion();\n",
             "  GpuLane::Get().Drain();  // [crackdown]\n"
             "  SubmitThread::Get().Drain();  // [submit thread]\n"
             "  AwaitAllQueueOperationsCompletion();\n")
    # only fences the thread has submitted are awaited or polled
    wait_scope = ("      " + perf_scope + "\n") if perf_scope else ""
    edit(cp, "  size_t fences_total = submissions_in_flight_fences_.size();\n"
             "  size_t fences_awaited = 0;\n",
         "  size_t fences_total = submissions_in_flight_fences_.size();\n"
         "  if (SubmitThread::Get().Running()) {\n"
         "    // [submit thread] only fences the thread has submitted are awaited or polled\n"
         "    if (await_submission > submission_completed_) {\n"
         + wait_scope +
         "      SubmitThread::Get().WaitSubmitted(await_submission);\n"
         "    }\n"
         "    const uint64_t submitted = SubmitThread::Get().Submitted();\n"
         "    fences_total = std::min(fences_total, submitted > submission_completed_\n"
         "                                              ? size_t(submitted - submission_completed_)\n"
         "                                              : size_t(0));\n"
         "  }\n"
         "  size_t fences_awaited = 0;\n")
    # EndSubmission: the submission handed to the thread, with the same bookkeeping as the inline path
    edit(cp, "    SubmitBarriers(true);\n\n"
             "    assert_false(command_buffers_writable_.empty());\n"
             "    CommandBuffer command_buffer = command_buffers_writable_.back();\n"
             "    if (dfn.vkResetCommandPool(device, command_buffer.pool, 0) != VK_SUCCESS) {\n",
         "    SubmitBarriers(true);\n\n"
         "    if (SubmitThread::Get().Active(this)) {\n"
         "      // [submit thread] replayed and submitted on the thread; the bookkeeping as below\n"
         "      assert_false(command_buffers_writable_.empty());\n"
         "      CommandBuffer command_buffer = command_buffers_writable_.back();\n"
         "      assert_false(fences_free_.empty());\n"
         "      VkFence fence = fences_free_.back();\n"
         "      if (dfn.vkResetFences(device, 1, &fence) != VK_SUCCESS) {\n"
         "        REXGPU_ERROR(\"Failed to reset a Vulkan submission fence\");\n"
         "        return false;\n"
         "      }\n"
         "      uint64_t submission_current = GetCurrentSubmission();\n"
         "      SubmitThread::Job job;\n"
         "      SubmitThread::Get().TakeSpare(job.stream);\n"
         "      deferred_command_buffer_.TakeStream(job.stream);\n"
         "      job.command_buffer = command_buffer.buffer;\n"
         "      job.pool = command_buffer.pool;\n"
         "      job.wait_semaphores = current_submission_wait_semaphores_;\n"
         "      job.wait_stage_masks = current_submission_wait_stage_masks_;\n"
         "      job.fence = fence;\n"
         "      job.submission = submission_current;\n"
         "      SubmitThread::Get().Push(std::move(job));\n"
         "      current_submission_wait_stage_masks_.clear();\n"
         "      for (VkSemaphore semaphore : current_submission_wait_semaphores_) {\n"
         "        submissions_in_flight_semaphores_.emplace_back(submission_current, semaphore);\n"
         "      }\n"
         "      current_submission_wait_semaphores_.clear();\n"
         "      command_buffers_submitted_.emplace_back(submission_current, command_buffer);\n"
         "      command_buffers_writable_.pop_back();\n"
         "      submissions_in_flight_fences_.push_back(fence);\n"
         "      fences_free_.pop_back();\n"
         "      submission_open_ = false;\n"
         "    } else {\n"
         "    assert_false(command_buffers_writable_.empty());\n"
         "    CommandBuffer command_buffer = command_buffers_writable_.back();\n"
         "    if (dfn.vkResetCommandPool(device, command_buffer.pool, 0) != VK_SUCCESS) {\n")
    edit(cp, "    submission_open_ = false;\n  }\n\n  if (is_closing_frame) {\n",
         "    submission_open_ = false;\n    }  // [submit thread] (the else)\n  }\n\n  if (is_closing_frame) {\n")
