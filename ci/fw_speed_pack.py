"""The framework speed pack: three GPU-thread fixes for any rex PS5 port, in one call (2026-11-05).

    import fw_speed_pack
    fw_speed_pack.apply(sdk, edit)          # at the END of your patch_framework.py main()

  sdk   the rexglue-sdk-main folder; edit: your edit(path, old, new) (it exits on a mismatch).
  Copy fw_speed_pack.py AND fw_submit_thread.py (Downloads/Recomps/speed-pack/) beside your
  patch_framework.py, and put that folder on sys.path first:
      sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

Every piece draws exactly the same pixels; each has its own cvar (set them in OnPreSetup with
rex::cvar::SetLaunchFlag, or in the port's toml):

1. gpu_skip_unchanged_writes (int, default 1)      - from Metal Gear Rising (mgr-ps5 45528e6)
   Xbox 360 games rewrite whole blocks of shader constants and fetch constants before most draws,
   mostly with the values already there. Each write threw away the uploaded constant buffer (the next
   draw allocated, copied and re-bound it) and, for fetch constants, every texture binding's key and
   the vertex buffers' residency. Now a write is compared with the register file as it is copied
   in: nothing changed, nothing invalidated; otherwise only the changed span. Every skipped cache
   would be rebuilt from the same register values.
   0 off, 1 on, 2 on and off in alternate 10 s windows (the same scene measured both ways).
   Log every 10 s: "speed pack: unchanged constant writes N of M a frame (P%), skipping ON|OFF".

2. gpu_wait_spin_us (int, default 2000)               - from Prototype (proto-ps5 4e11118)
   Past its first 16 polls a WAIT_REG_MEM slept 1 ms at a time, woken early only by a vblank, so a
   value the game wrote just after a poll waited out the rest of the millisecond (Prototype 2: 27
   waits a frame, 10.5 ms of the GPU thread's 16.7). It now keeps polling (with yields: the GPU
   thread has a CPU of its own) for up to this many microseconds before sleeping. Same result, sooner.
   0: as before.

3. gpu_submit_thread (bool, default true)             - from Driver SF (dsf-ps5 815c67e)
   EndSubmission's replay of the recorded commands into Vulkan plus vkQueueSubmit (Driver SF 3-5.5 ms
   a frame in its dips, SR2 ~8.5, Crackdown 2 11-12) run on a thread of their own (CPU `cpu`, 5 by
   default) while the GPU thread records the next submission. Same commands, same order, same queue
   order. Details in fw_submit_thread.py.

Pass skip=False / spin=False / submit=False for a piece your port already has in another form
(The Darkness and Prototype took 1 and 2 earlier; Saints Row has sr_submit_thread; Crackdown has
cd_wait_spin_us and cd_submit_thread). perf_scope: as in fw_submit_thread.py (optional).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fw_submit_thread  # noqa: E402


def apply(sdk, edit, skip=True, spin=True, submit=True, cpu=5, perf_scope=None,
          skip_default=1, spin_default_us=2000, submit_default=True):
    sdk = pathlib.Path(sdk)
    if skip:
        skip_unchanged_writes(sdk, edit, skip_default)
    if spin:
        wait_spin(sdk, edit, spin_default_us)
    if submit:
        fw_submit_thread.submit_thread(sdk, edit, cvar="gpu_submit_thread", cpu=cpu,
                                       default_on=submit_default, perf_scope=perf_scope)


def skip_unchanged_writes(sdk, edit, default):
    vcp = sdk / "src" / "graphics" / "vulkan" / "command_processor.cpp"
    edit(vcp,
         'REXCVAR_DEFINE_BOOL(vulkan_dynamic_rendering, true, "GPU/Vulkan",\n',
         'REXCVAR_DEFINE_INT32(gpu_skip_unchanged_writes, ' + str(default) + ', "GPU",\n'
         '                     "[speed pack] Constant register writes that change no value invalidate nothing "\n'
         '                     "(0 off, 1 on, 2 on and off in alternate 10 s windows, to measure it)")\n'
         '    .range(0, 2);\n\n'
         'REXCVAR_DEFINE_BOOL(vulkan_dynamic_rendering, true, "GPU/Vulkan",\n')
    edit(vcp,
         "void VulkanCommandProcessor::WriteRegister(uint32_t index, uint32_t value) {\n"
         "  CommandProcessor::WriteRegister(index, value);\n",
         "// [speed pack] gpu_skip_unchanged_writes (GPU thread only: plain counters)\n"
         "static uint64_t speed_pack_writes = 0, speed_pack_skips = 0;\n"
         "static bool speed_pack_window_on = true;\n"
         "static bool SpeedPackSkipOn() {\n"
         "  const int32_t mode = REXCVAR_GET(gpu_skip_unchanged_writes);\n"
         "  return mode == 1 || (mode == 2 && speed_pack_window_on);\n"
         "}\n"
         "// (copies the guest's big-endian values into the registers; the span that changed in lo..hi,\n"
         "// false when none did)\n"
         "static bool SpeedPackCopyChanged(uint32_t* dst, const uint32_t* src, uint32_t count, uint32_t& lo,\n"
         "                                 uint32_t& hi) {\n"
         "  lo = UINT32_MAX, hi = 0;\n"
         "  for (uint32_t i = 0; i < count; ++i) {\n"
         "    const uint32_t value = memory::load_and_swap<uint32_t>(src + i);\n"
         "    if (dst[i] != value) {\n"
         "      dst[i] = value;\n"
         "      if (lo == UINT32_MAX) lo = i;\n"
         "      hi = i;\n"
         "    }\n"
         "  }\n"
         "  return lo != UINT32_MAX;\n"
         "}\n"
         "// (every 10 s from IssueSwap: the counts, then in mode 2 the next window's state)\n"
         "static void SpeedPackReport() {\n"
         "  static uint64_t last_us = 0, frames = 0;\n"
         "  const int32_t mode = REXCVAR_GET(gpu_skip_unchanged_writes);\n"
         "  const uint64_t now = uint64_t(std::chrono::duration_cast<std::chrono::microseconds>(\n"
         "                                   std::chrono::steady_clock::now().time_since_epoch()).count());\n"
         "  ++frames;\n"
         "  if (!last_us) {\n"
         "    last_us = now, frames = 0, speed_pack_writes = speed_pack_skips = 0;\n"
         "    return;\n"
         "  }\n"
         "  if (now - last_us < 10000000 || !frames) return;\n"
         "  if (mode) {\n"
         "    REXGPU_INFO(\"speed pack: unchanged constant writes {:.0f} of {:.0f} a frame ({:.0f}%), skipping {}\",\n"
         "                double(speed_pack_skips) / frames, double(speed_pack_writes) / frames,\n"
         "                speed_pack_writes ? 100.0 * speed_pack_skips / speed_pack_writes : 0.0,\n"
         "                mode == 1 || speed_pack_window_on ? \"ON\" : \"OFF\");\n"
         "    if (mode == 2) speed_pack_window_on = !speed_pack_window_on;\n"
         "  }\n"
         "  last_us = now, frames = 0, speed_pack_writes = speed_pack_skips = 0;\n"
         "}\n"
         "\n"
         "void VulkanCommandProcessor::WriteRegister(uint32_t index, uint32_t value) {\n"
         "  if (index >= XE_GPU_REG_SHADER_CONSTANT_000_X && index <= XE_GPU_REG_SHADER_CONSTANT_LOOP_31 &&\n"
         "      (index <= XE_GPU_REG_SHADER_CONSTANT_FETCH_31_5 ||\n"
         "       index >= XE_GPU_REG_SHADER_CONSTANT_BOOL_000_031)) {\n"
         "    ++speed_pack_writes;  // [speed pack] a constant written with its own value: nothing to do\n"
         "    if (SpeedPackSkipOn() && register_file_->values[index] == value) {\n"
         "      ++speed_pack_skips;\n"
         "      return;\n"
         "    }\n"
         "  }\n"
         "  CommandProcessor::WriteRegister(index, value);\n")
    take = ("    ++speed_pack_writes;  // [speed pack]\n"
            "    if (SpeedPackSkipOn()) {\n"
            "      uint32_t lo, hi;\n"
            "      if (!SpeedPackCopyChanged(register_file_->values + start_index, base, num_registers, lo, hi)) {\n"
            "        ++speed_pack_skips;\n"
            "        return;\n"
            "      }\n"
            "      sp_first = start_index + lo, sp_last = start_index + hi;\n"
            "    } else {\n"
            "      memory::copy_and_swap(register_file_->values + start_index, base, num_registers);\n"
            "    }\n")
    # float constants: only the changed span is checked against the shaders' constant maps
    edit(vcp,
         "    memory::copy_and_swap(register_file_->values + start_index, base, num_registers);\n"
         "    if (frame_open_) {\n"
         "      uint32_t first_float_constant = (start_index - XE_GPU_REG_SHADER_CONSTANT_000_X) >> 2;\n"
         "      uint32_t last_float_constant = (end_index - XE_GPU_REG_SHADER_CONSTANT_000_X) >> 2;\n",
         "    uint32_t sp_first = start_index, sp_last = end_index;  // [speed pack] the changed span\n"
         + take +
         "    if (frame_open_) {\n"
         "      uint32_t first_float_constant = (sp_first - XE_GPU_REG_SHADER_CONSTANT_000_X) >> 2;\n"
         "      uint32_t last_float_constant = (sp_last - XE_GPU_REG_SHADER_CONSTANT_000_X) >> 2;\n")
    # bool / loop constants
    edit(vcp,
         "      end_index <= XE_GPU_REG_SHADER_CONSTANT_LOOP_31) {\n"
         "    memory::copy_and_swap(register_file_->values + start_index, base, num_registers);\n"
         "    current_constant_buffers_up_to_date_ &=\n",
         "      end_index <= XE_GPU_REG_SHADER_CONSTANT_LOOP_31) {\n"
         "    uint32_t sp_first = start_index, sp_last = end_index;  // [speed pack]\n"
         + take +
         "    (void)sp_first, (void)sp_last;\n"
         "    current_constant_buffers_up_to_date_ &=\n")
    # fetch constants: the texture bindings and vertex buffers of the changed span only
    edit(vcp,
         "      end_index <= XE_GPU_REG_SHADER_CONSTANT_FETCH_31_5) {\n"
         "    memory::copy_and_swap(register_file_->values + start_index, base, num_registers);\n"
         "    current_constant_buffers_up_to_date_ &=\n"
         "        ~(UINT32_C(1) << SpirvShaderTranslator::kConstantBufferFetch);\n"
         "    uint32_t first_fetch_dword = start_index - XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0;\n"
         "    uint32_t last_fetch_dword = end_index - XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0;\n",
         "      end_index <= XE_GPU_REG_SHADER_CONSTANT_FETCH_31_5) {\n"
         "    uint32_t sp_first = start_index, sp_last = end_index;  // [speed pack] the changed span\n"
         + take +
         "    current_constant_buffers_up_to_date_ &=\n"
         "        ~(UINT32_C(1) << SpirvShaderTranslator::kConstantBufferFetch);\n"
         "    uint32_t first_fetch_dword = sp_first - XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0;\n"
         "    uint32_t last_fetch_dword = sp_last - XE_GPU_REG_SHADER_CONSTANT_FETCH_00_0;\n")
    edit(vcp,
         "void VulkanCommandProcessor::IssueSwap(uint32_t frontbuffer_ptr, uint32_t frontbuffer_width,\n"
         "                                       uint32_t frontbuffer_height) {\n",
         "void VulkanCommandProcessor::IssueSwap(uint32_t frontbuffer_ptr, uint32_t frontbuffer_width,\n"
         "                                       uint32_t frontbuffer_height) {\n"
         "  SpeedPackReport();  // [speed pack]\n")


def wait_spin(sdk, edit, default_us):
    cpc = sdk / "src" / "graphics" / "command_processor.cpp"
    edit(cpc, 'REXCVAR_DEFINE_BOOL(vsync, true, "GPU", "Enable vertical sync");\n',
         'REXCVAR_DEFINE_BOOL(vsync, true, "GPU", "Enable vertical sync");\n'
         'REXCVAR_DEFINE_INT32(gpu_wait_spin_us, ' + str(default_us) + ', "GPU",\n'
         '                     "[speed pack] WAIT_REG_MEM keeps polling (yielding) this long before it sleeps 1 ms "\n'
         '                     "at a time (0: the 16 polls of before)");\n'
         '#include <chrono>  // [speed pack]\n')
    edit(cpc,
         "  uint32_t unmatched_poll_count = 0;\n  bool matched = false;\n  do {\n",
         "  uint32_t unmatched_poll_count = 0;\n  bool matched = false;\n"
         "  // [speed pack] polled (with yields) for up to gpu_wait_spin_us before any 1 ms sleep\n"
         "  const auto speed_pack_wait_start = std::chrono::steady_clock::now();\n"
         "  const auto speed_pack_spin = std::chrono::microseconds(REXCVAR_GET(gpu_wait_spin_us));\n"
         "  do {\n")
    edit(cpc,
         "        if (unmatched_poll_count < kYieldPollCount || !REXCVAR_GET(vsync)) {\n",
         "        if (unmatched_poll_count < kYieldPollCount || !REXCVAR_GET(vsync) ||\n"
         "            std::chrono::steady_clock::now() - speed_pack_wait_start < speed_pack_spin) {\n")
