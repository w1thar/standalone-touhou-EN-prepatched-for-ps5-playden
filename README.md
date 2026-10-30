# Touhou EN standalone for PS5 (Playden)

Turns **your own** copy of Touhou 8 (Imperishable Night) or Touhou 11 (Subterranean Animism), patched to English
with [thcrap](https://www.thpatch.net/wiki/Touhou_Patch_Center), into a folder that
[Playden](https://github.com/leolobato/playden-ps5) can run on a jailbroken PS5.

**No game files are included.** You need the original games. 
Recommendation: [Moriya Shrine](https://moriyashrine.org/resources/)

## Why this is needed

thcrap normally starts the game through `thcrap_loader.exe`, which launches the game exe and injects the patch.
Playden can't start a second process, so the launcher never works on the PS5. This kit:

- adds a small loader to the game exe itself. The exe loads `thcrap\bin\thcrap.dll` and calls `thcrap_init`
  before the game starts, so no launcher or Locale Emulator is needed;
- registers the patched exe in thcrap's `versions.js`, so thcrap still recognises the game;
- patches `win32_utf8.dll`: `GetStartupInfoU` doesn't check `lpDesktop`/`lpTitle` for NULL, which they are
  under Playden's Wine, so the game crashed at start;
- **Touhou 8 only:** the game checks its own exe's size and checksum, which the patched exe fails. A thcrap patch
  makes that check pass. thcrap's `TH8ScorefileFixer` hook is removed, because it writes to read-only memory and
  crashes on the PS5;
- makes a 512×512 `icon0.png` from the game's icon for the Home screen (see below).

## Requirements

- Touhou 8 **v1.00d** (`th08.exe`) or Touhou 11 **v1.00a** (`th11.exe`), the original Japanese exe.
- thcrap set up in the game folder with the English (`thpatch-en`) configuration, as `thcrap_configure` makes it
  (a `thcrap` folder next to the exe). Update thcrap first: these packages were tested on the PS5 with thcrap
  **2026-10-21 (stable)**.
- Python 3.10+ and `pip install keystone-engine pefile pillow`.

## Make the package

```sh
python make_ps5_package.py "path/to/Touhou 11 - Subterranean Animism" "out/Touhou 11 - Subterranean Animism"
python make_ps5_package.py "path/to/Touhou 8 - Imperishable Night"   "out/Touhou 8 - Imperishable Night" --copy-saves
```

`--copy-saves` also copies your score file and settings (`score.dat`/`th08.cfg`, `scoreth11.dat`/`th11.cfg`).
The output folder has the patched exe, the game data, the 32-bit thcrap runtime with its patches, and `icon0.png`.

## Put it on the PS5

1. Copy the output folder to `/data/playden-import/<folder>` over FTP, or to `playden/import/<folder>` on a USB drive.
2. In Playden choose **Import games**, pick the folder, and choose `th08.exe` or `th11.exe` as the program.
3. Start it from Playden.

Playden folder paths must be plain ASCII.

## Home screen icon (optional)

Playden gives imported games a generic icon, and has no setting to change it. To use `icon0.png`, overwrite it
**in place** at all five of these locations. Find your game's `FAKE78xxx` title ID in
`/data/homebrew/FAKE78*/sce_sys/param.json`:

| | Path |
|---|---|
| Playden's copy | `/data/playden/games/local-<id>/title-metadata/sce_sys/icon0.png` |
| Installed title | `/data/homebrew/<FAKE78xxx>/sce_sys/icon0.png` |
| Home screen | `/user/appmeta/<FAKE78xxx>/icon0.png` |
| | `/user/app/<FAKE78xxx>/sce_sys/icon0.png` |
| | `/user/app/<FAKE78xxx>/icon0.png` |

The first two must be the same file, or Playden puts the generic icon back. Reboot to see the change.

> **Never change permissions (chmod, e.g. FileZilla's "File permissions") under `/data/playden` or `/data/homebrew`.**
> Each game's tile refuses to start unless its private folders are exactly `0700` and its files `0600`. Afterwards
> every game fails with `publication refused reason=invalid publication roots`. If it happened:
> - set the folders of `/data/playden/games/<id>` back to `700` (directories only, recursive);
> - set the files directly in `library/profiles`, `library/input`, `.playden-control` and `library/prefixes/game`
>   back to `600`;
> - set `/data/homebrew/<FAKE78xxx>/game-launch.json` to `600`;
> - set the folders of `/data/playden-games/<id>` to `755`;
>
> then start each game once from inside Playden.

## Troubleshooting

thcrap writes its log to `thcrap/logs/thcrap_log.txt` in the game folder. On a crash it ends with the exception and
the address, which is the first thing to look at. Playden's own logs are in `/data/playden/logs/`.
WHEN USING FILEZILLA OR PROSPEROMANAGER BE CAREFUL ABOUT CHANGING PERMISSIONS BECAUSE PLAYDEN ONLY WORKS WITH SPECIFIC PERMISSION LEVELS ON FILES/FOLDERS SO DON'T FORGET TO SET THOSE BACK (so if a file had the file permission of 644 then remember to set it back to that after you're done with it)

## Status

| Game | Status |
|---|---|
| Touhou 11 v1.00a | Works on PS5 (Playden) with the English patch. |
| Touhou 8 v1.00d | Starts and reaches the title screen on PS5. The exe-check fix for starting a game is new; but mostly works. |

Not affiliated with Team Shanghai Alice, the Touhou Patch Center or Playden.
