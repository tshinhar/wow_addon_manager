# WoW Addon Manager

A simple addon manager tool for **World of Warcraft** and **World of Warcraft Forever**.

## Features

1. **World of Warcraft & World of Warcraft Forever Support**:
   - Manage separate install directories (`addons_path` and `wow_forever_addons_path` in `settings.json`) and separate addon lists (`wow` and `wow_forever` in `addons.json`).
   - Switch between games at any time from the UI or CLI.
2. **Graphical User Interface (GUI) & CLI**:
   - Launches a Tkinter desktop UI by default.
   - Pass `--cli` (`python main.py --cli` or `wow_addon_manager.exe --cli`) to use the command-line menu.
3. **Self-Update**:
   - Update your local installation of `wow_addon_manager` directly from the latest GitHub release while preserving your local `settings.json` and `addons.json`.

## How to Use

1. Launch `wow_addon_manager` (or run `python main.py`).
2. Select **World of Warcraft** or **World of Warcraft Forever** and set the corresponding **Addons Path** to the folder where your addons should be extracted.
3. Add the GitHub repository URLs or CurseForge numeric project IDs of the addons you want installed.
4. Click **Update All Addons** (or **Update Selected**) to download and extract the latest versions into the active game's addons folder.
5. Click **Self Update (GitHub Release)** to check for and install the latest release of `wow_addon_manager`.

## Notes

- You can manage settings and addon lists directly through the UI/CLI or by manually editing `settings.json` and `addons.json`.
- Built with PyInstaller for standalone execution on systems without Python installed.
