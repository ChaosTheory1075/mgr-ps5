# Metal Gear Rising: Revengeance RePlatinum

Metal Gear Rising: Revengeance (Xbox 360, 2013) recompiled to run natively on the PS5, by ChaosTheory1075.

> Built on [elripalda's GTA IV for PS5](https://github.com/elripalda/gta4-ps5), with GPU and timing
> work from [saulob's Crackdown Recompiled](https://github.com/saulob/crackdown-xbox360-recompiled).
> All the credit goes to them. Go star the original projects and support them.

An unofficial fan project, not affiliated with or endorsed by Konami, PlatinumGames, Microsoft or
Sony. **No game files are included:** you need your own copy of Metal Gear Rising: Revengeance for
the Xbox 360.

## What's in it
- Metal Gear Rising: Revengeance with Title Update 4, recompiled to run natively on the PS5 (not
  emulated)
- 60 FPS, as the game was made
- Optional HD cutscenes: the 1080p 60 FPS cutscene pack from Nexus Mods, installed on the console
  from its two zips
- PlayStation button prompts and controller pictures (or the Xbox 360's)
- DualSense: the light bar follows Raiden's health, adaptive triggers for Blade Mode and Ninja Run,
  stronger rumble
- A cheat quick menu: L3 + R3 in game for Infinite Health and Infinite Fuel Cells
- English, French, German, Italian, Spanish or Portuguese (Brazil) text, or the PS5's own language;
  in Portuguese the menu, the quick menu and the trophy pop-ups are in Portuguese too
- FSR 1 upscaling to 4K with a sharpness setting, SMAA or FXAA, anisotropic filtering (2x to 16x), an
  FPS counter, Skip Intro and an experimental FAST renderer
- The DLC: Jetstream, Blade Wolf, the VR Mission Expansion and the costumes
- The game's achievements as PS5-style trophies, with their own page in the menu
- Installs the game, Title Update 4 and the DLC from your own files, at the drive's full speed
- Imports your Xbox 360 saves, backs up and restores saves
- A menu with HOME, CONTENT, SAVES, SETTINGS, TROPHIES and CREDITS pages, its own art and music

## What you need
- A jailbroken PS5 that runs homebrew apps, with a payload loader on port 9021 (etaHEN or elfldr)
- Your **own** Metal Gear Rising: Revengeance for the Xbox 360, as an `.iso` file or the disc's files
- Title Update 4 (required). The base game and other title updates aren't supported
- Optional: the DLC packages

## Which files work

| | File | Size |
|---|---|---|
| Game | `Metal Gear Rising - Revengeance (World) (En,Ja,Fr,De,Es,It,Pt).iso` (any name) | |
| Title Update 4 | `tu00000001_00000000` | 66,215,936 bytes |
| DLC | the packages in `4B4E080A/00000002` (named like `4C526F5275130ABB7264B6E8FDFD1AC461C2EBFC4B`) | |

The packages have no file extension; that's normal. Any file name works: the app tells what each
file is from what's in it.

## Install
1. Copy the `PPSA48080` folder from the release `.zip` to the PS5, wherever your homebrew loader
   looks (`/data/homebrew/`, `/mnt/ext0/homebrew/`, `/mnt/usb0/homebrew/`, ...).
2. Put your disc image (or the disc's files), Title Update 4 and the DLC packages in
   `PPSA48080/install/`. Extract any `.7z`, `.rar` or `.zip` on a PC first.
3. Open **Metal Gear Rising: Revengeance RePlatinum**. It installs everything it finds, one at a
   time, then asks whether to delete the files it installed from.
4. When PLAY lights up, you're set.

To import a save, put the Xbox 360 save package (copied off the 360's drive) in `install/` and import
it from the SAVES page. It loads the next time you press PLAY.

See [package/README.txt](package/README.txt) for the rest: the menu's pages, your data and backups,
updating to a new build, and [package/install-README.txt](package/install-README.txt) for what goes
in `install/`.

## Build from source
The build runs on Ubuntu 24.04 (WSL works), as root, with your own game files:

```bash
bash tools/local/toolchain.sh   # the PS5 toolchain (ps5-plume-triangle), once
bash tools/local/framework.sh   # gta4-ps5's framework and the Crackdown PC recomp's patches, once
MGR_XEX=<the disc's default.xex> MGR_XEXP=<Title Update 4's default.xexp> \
  bash tools/local/build.sh . <where to put the PPSA48080 folder>
```

The build checks the two files by their SHA-1s. It applies `ci/pc_patches.py`,
`ci/fw_perf_fixes.py` and `ci/patch_framework.py` to gta4-ps5's framework, recompiles the game
(ReXGlue codegen), builds and signs the program and the installer payload
(`ps5/payload/installer`), and packages the app folder.

## Credits
- **elripalda**: [GTA IV for PS5](https://github.com/elripalda/gta4-ps5), the PS5 port this one is
  built on: the runtime, graphics and sound, the menu, trophies, the installer payload
- **saulob**: [Crackdown Recompiled](https://github.com/saulob/crackdown-xbox360-recompiled), whose
  ReXGlue patches and frame rate work this port's GPU and timing fixes come from
- **OZORDI** and **vaduur**: Liberty Recompiled and LibertyRecompAndroid, which GTA IV for PS5 starts from
- **ReXGlue** and the **Xenia** team: the static recompiler, the runtime and the Xbox 360 emulation
  it grew from
- **Crackdown: ReActivated** and **Max Payne 3 RePrescribed** (ChaosTheory1075): the sister ports
  whose menu, installer, saves and trophies this one shares
- **BlackBearReloaded**: the PS5 AT9 Converter (the home screen music)
- The makers of **MGRR FULLHD 60FPS CUTSCENE UPSCALE**
  ([Nexus Mods](https://www.nexusmods.com/metalgearrisingrevengeance/mods/505)), the HD cutscenes
  the app installs (download them from there)
- **chronicer**: [mgrCheatSamQTE](https://github.com/chronicer/mgrCheatSamQTE), whose PC game
  structures pointed the way to the cheats
- Built with the PS5 Payload SDK, Mesa RADV, Dear ImGui, stb_image, dr_mp3, and the Oswald and Inter
  fonts (SIL Open Font License)
- Special thanks to **PlatinumGames** and **Kojima Productions**, for Metal Gear Rising

## License
The code in this repository is licensed under the GNU General Public License v3.0 (see
[LICENSE](LICENSE)), as GTA IV for PS5 is. Third-party components keep their own licenses. The
build also uses patches from saulob's Crackdown Recompiled, which is licensed under GPL-2.0-only.
No game files are included, and Metal Gear Rising: Revengeance's game assets are not covered by this
license. Metal Gear and all related names belong to their owners.
