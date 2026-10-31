# Metal Gear Rising: Revengeance: the recompiled game and its app, built inside gta4-ps5's tree
# (glue/rexglue-sdk-main/mgr-recomp, see .github/workflows/ps5-build.yml) as
# one static PS5 program, the way gta4-recomp builds GTA IV.

if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/generated/sources.cmake")
    message(FATAL_ERROR "mgr-recomp generated sources are missing: run rexglue codegen mgr_manifest.toml")
endif()
include(generated/sources.cmake)

set(MGR_APP_SOURCES
    src/main.cpp
    src/mgr_app.cpp
)

if(PS5)
    # The menu (its fonts: gta4-ps5's, SIL Open Font License) and gta4-ps5's
    # own sound mixer for its song.
    set(GTA4_PS5_SRC "${REXSDK_DIR}/gta4-recomp/src/ps5")
    set(MGR_PS5_FONTS "${REXSDK_DIR}/../../ps5/assets/fonts")
    list(APPEND MGR_APP_SOURCES src/ps5/mgr_menu.cpp src/ps5/mgr_install.cpp src/ps5/mgr_trophies.cpp src/ps5/mgr_trophies_game.cpp src/ps5/mgr_game_overlay.cpp
         "${GTA4_PS5_SRC}/game/sound.cpp" "${GTA4_PS5_SRC}/hub/hub_sfx.cpp")
    set_source_files_properties(src/ps5/mgr_menu.cpp PROPERTIES
        COMPILE_DEFINITIONS "MGRPS5_FONTS_DIR=\"${MGR_PS5_FONTS}\"")
    add_executable(mgr ${MGR_APP_SOURCES} ${GENERATED_SOURCES})
    target_include_directories(mgr PRIVATE "${GTA4_PS5_SRC}")
    # The recompiled game's own files, as gta4-recomp marks GTA IV's.
    set(MGR_PS5_GUEST_SOURCES ${GENERATED_SOURCES})
    list(FILTER MGR_PS5_GUEST_SOURCES INCLUDE REGEX "mgr_recomp\\.[0-9]+\\.cpp$")
    set_property(SOURCE ${MGR_PS5_GUEST_SOURCES} APPEND PROPERTY COMPILE_DEFINITIONS REX_PS5_GUEST_CODE=1)
    set_property(SOURCE generated/mgr_register.cpp APPEND PROPERTY COMPILE_OPTIONS
        "$<$<CONFIG:Release,RelWithDebInfo>:-O0>")
    target_compile_definitions(mgr PRIVATE REX_FUSED_VMADDFP=1)
    target_include_directories(mgr PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_SOURCE_DIR}/generated
        ${CMAKE_CURRENT_SOURCE_DIR}/../thirdparty/crypto
        ${CMAKE_CURRENT_SOURCE_DIR}/../thirdparty/imgui
        ${CMAKE_CURRENT_SOURCE_DIR}/../thirdparty/inja/third_party/include
        ${CMAKE_CURRENT_SOURCE_DIR}/../thirdparty/stb
    )
    target_compile_options(mgr PRIVATE "SHELL:-include ${REXSDK_DIR}/include/rex/ps5_compat.h")
    target_link_libraries(mgr PRIVATE
        rex::runtime
        rexgpu-xenos
        xxHash::xxhash
        SDL3::SDL3
        SceUserService ScePad SceAudioOut SceSystemService SceVideoOut
    )
    rexglue_configure_target(mgr)
else()
    add_executable(mgr ${MGR_APP_SOURCES} ${GENERATED_SOURCES})
    target_include_directories(mgr PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_SOURCE_DIR}/generated
        ${CMAKE_CURRENT_SOURCE_DIR}/../thirdparty/imgui
    )
    target_link_libraries(mgr PRIVATE rex::runtime)
    rexglue_configure_target(mgr GPU_PLUGINS xenos)
endif()
