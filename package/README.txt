Metal Gear Rising: Revengeance RePlatinum
=========================================

Metal Gear Rising: Revengeance (Xbox 360, Title Update 4) recompiled to run
natively on the PS5, at 60 fps, with its DLC, your saves and its achievements
as trophies. An unofficial fan project: no game files are included, you need
your own copy of Metal Gear Rising: Revengeance.

What you need
-------------
- A PS5 that runs homebrew apps from /data/homebrew/ or homebrew/ on an
  external drive.
- Your Metal Gear Rising: Revengeance disc image (.iso), or the disc's files.
- Title Update 4's package (tu00000001_00000000).
- Optional: the DLC packages (Jetstream, Blade Wolf, the VR missions, the
  costumes).

Install
-------
1. Copy this whole PPSA48080 folder to the PS5's homebrew folder
   (/data/homebrew/, or homebrew/ on an external drive).
2. Put these in PPSA48080/install/ (see install/README.txt):
   - your disc image (.iso, any name), or a folder of the disc's files,
   - Title Update 4's package (required),
   - the DLC packages (optional).
   Extract any .7z / .rar / .zip on a PC first.
3. Open "Metal Gear Rising: Revengeance RePlatinum". It installs what it
   finds, one at a time, with the progress on its HOME page (the disc image
   takes a few minutes). When PLAY lights up, you're set; the CONTENT page
   shows what's installed. At the end it asks whether to delete the files it
   installed from (X) or keep them (O).

The menu
--------
HOME      PLAY; an install's progress; what's missing and where it goes.
CONTENT   the game, Title Update 4 and the DLC: installed or not, X installs
          one from install/, triangle (twice) uninstalls it.
SAVES     BACK UP SAVES (to install/backups/), IMPORT an Xbox 360 save
          package from install/, RESTORE one of the backups.
SETTINGS  ANTI-ALIASING     off or FXAA.
          TEXTURE FILTERING 2x to 16x anisotropic.
          GPU HELPER        a second graphics thread (on); turn it off if
                            something draws wrong.
          MENU MUSIC        the menu song's level.
TROPHIES  every achievement, earned ones first, with their dates (filled in
          once the game has been started once).
CREDITS   who made it possible.
L1 / R1 change pages, O goes back to HOME. Settings are kept in menu.ini.

Your data (back these up before deleting or reinstalling the app!)
------------------------------------------------------------------
- PPSA48080/saves/          your game saves
- PPSA48080/UserData/       trophies (earned and their dates) and the shader cache
- PPSA48080/menu.ini        your settings
SAVES > BACK UP SAVES copies the saves, trophies and settings to
PPSA48080/install/backups/: copy that folder off the PS5. Deleting the
PPSA48080 folder deletes them too.

The first time each area is seen, its shaders are built and saved: the
first play-through can stutter now and then; later sessions load them.

Updating to a new build
-----------------------
Replace eboot.bin, sce_sys/ and sce_module/ (and hub/ and payloads/ if they
changed). Keep game/, dlc/, install/, saves/, UserData/ and menu.ini.

Problems
--------
- PLAY stays grey: the HOME and CONTENT pages say what's missing.
- An install failed: the CONTENT page says why (not enough space, not the
  right file, ...). Fix it and press X on that row.
- Something draws wrong: SETTINGS > GPU HELPER off.
- The home screen tile, background or music didn't change after an update:
  restart the PS5 (it caches them).
- A log of every run is written to PPSA48080/logs/. Send the newest one with
  any report.

Credits
-------
Built on elripalda's GTA IV for PS5 (github.com/elripalda/gta4-ps5), saulob's
Crackdown Recompiled (github.com/saulob/crackdown-xbox360-recompiled), OZORDI's
Liberty Recompiled and vaduur's LibertyRecompAndroid, ReXGlue and Xenia.
Hover music made with BlackBearReloaded's PS5 AT9 Converter.
Special thanks to PlatinumGames and Kojima Productions, for Metal Gear Rising.

Metal Gear and all related names belong to their owners. This project is not
affiliated with or endorsed by Konami, PlatinumGames, Microsoft or Sony.
