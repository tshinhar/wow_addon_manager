"""
this is the main section of the wow addon manager
created by tshinhar
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
import requests

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    from tkinter.scrolledtext import ScrolledText
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

GAME_WOW = "wow"
GAME_WOW_FOREVER = "wow_forever"

GAME_LABELS = {
    GAME_WOW: "World of Warcraft",
    GAME_WOW_FOREVER: "World of Warcraft Forever",
}

GAME_PATH_KEYS = {
    GAME_WOW: "addons_path",
    GAME_WOW_FOREVER: "wow_forever_addons_path",
}

SELF_UPDATE_REPO = "tshinhar/wow_addon_manager"
DEFAULT_VERSION = "1.0.0"

settings = {}
addons = {}
zip_names = []


def get_app_dir():
    """Return the directory containing the application executable or script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path(filename):
    """Resolve config file path, checking CWD first then application directory."""
    if os.path.exists(filename):
        return os.path.abspath(filename)
    app_path = os.path.join(get_app_dir(), filename)
    return app_path


def normalize_settings(raw_settings):
    """Ensure settings dictionary contains all required keys for WoW and WoW Forever."""
    if not isinstance(raw_settings, dict):
        raw_settings = {}
    normalized = {
        "addons_path": raw_settings.get("addons_path", ""),
        "wow_forever_addons_path": raw_settings.get("wow_forever_addons_path", ""),
        "active_game": raw_settings.get("active_game", GAME_WOW),
        "version": raw_settings.get("version", DEFAULT_VERSION),
    }
    if normalized["active_game"] not in GAME_LABELS:
        normalized["active_game"] = GAME_WOW
    for k, v in raw_settings.items():
        if k not in normalized:
            normalized[k] = v
    return normalized


def normalize_addons(raw_addons):
    """Ensure addons dictionary has separate sections for 'wow' and 'wow_forever'."""
    if not isinstance(raw_addons, dict):
        return {GAME_WOW: {}, GAME_WOW_FOREVER: {}}

    if GAME_WOW in raw_addons or GAME_WOW_FOREVER in raw_addons:
        wow_addons = raw_addons.get(GAME_WOW, {})
        forever_addons = raw_addons.get(GAME_WOW_FOREVER, {})
        if isinstance(wow_addons, dict) and isinstance(forever_addons, dict):
            return {
                GAME_WOW: dict(wow_addons),
                GAME_WOW_FOREVER: dict(forever_addons),
            }

    # Migrate legacy flat addons dictionary into the 'wow' profile
    migrated_wow = {
        k: v for k, v in raw_addons.items() if isinstance(v, str)
    }
    return {
        GAME_WOW: migrated_wow,
        GAME_WOW_FOREVER: {},
    }


def load_settings(filepath=None):
    """Load and normalize settings from settings.json."""
    global settings
    path = filepath or get_config_path("settings.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as sf:
            data = json.load(sf)
    else:
        data = {}
    settings = normalize_settings(data)
    return settings


def save_settings(filepath=None):
    """Save current settings to settings.json."""
    path = filepath or get_config_path("settings.json")
    with open(path, "w", encoding="utf-8") as sfile:
        json.dump(settings, sfile, indent=4)


def load_addons(filepath=None):
    """Load and normalize addons from addons.json."""
    global addons
    path = filepath or get_config_path("addons.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as af:
            data = json.load(af)
    else:
        data = {}
    addons = normalize_addons(data)
    return addons


def save_addons(filepath=None):
    """Save current addons to addons.json."""
    path = filepath or get_config_path("addons.json")
    with open(path, "w", encoding="utf-8") as afile:
        json.dump(addons, afile, indent=4)


def get_active_game():
    """Return the currently selected game key ('wow' or 'wow_forever')."""
    game = settings.get("active_game", GAME_WOW)
    if game not in GAME_LABELS:
        game = GAME_WOW
    return game


def set_active_game(game):
    """Set the currently active game key ('wow' or 'wow_forever')."""
    if game not in GAME_LABELS:
        raise ValueError(f"Unsupported game: {game}")
    settings["active_game"] = game


def get_game_addons_path(game=None):
    """Get the addons install directory path for the given game."""
    game = game or get_active_game()
    path_key = GAME_PATH_KEYS.get(game, "addons_path")
    return settings.get(path_key, "")


def set_game_addons_path(path, game=None):
    """Set the addons install directory path for the given game."""
    game = game or get_active_game()
    path_key = GAME_PATH_KEYS.get(game, "addons_path")
    settings[path_key] = path


def get_game_addons(game=None):
    """Get the dictionary of addons for the specified game."""
    global addons
    game = game or get_active_game()
    if not isinstance(addons, dict) or game not in addons or not isinstance(addons.get(game), dict):
        addons = normalize_addons(addons)
    return addons[game]


def parse_github_repo(url):
    """Extract (owner, repo) from a GitHub URL or owner/repo string."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if "github.com/" in cleaned:
        cleaned = cleaned.split("github.com/", 1)[1]
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid GitHub repository URL: {url}")
    return parts[0], parts[1]


def get_installed_addon_dirs(game=None):
    """Return list of installed addon folder names in the target game's addons path."""
    path = get_game_addons_path(game)
    if not path or not os.path.isdir(path):
        return []
    return sorted([
        d for d in os.listdir(path)
        if os.path.isdir(os.path.join(path, d))
    ])


def update(game=None, addon_filter=None, log_func=print, prompt_source_func=None):
    """Update currently listed addons for the selected game to their latest version."""
    game = game or get_active_game()
    game_label = GAME_LABELS.get(game, game)
    game_addons = get_game_addons(game)
    addons_path = get_game_addons_path(game)

    if not addons_path:
        log_func(f"Error: Addons path for {game_label} is not set in settings!")
        return 1

    if not game_addons:
        log_func(f"No addons configured for {game_label}.")
        return 0

    os.makedirs(addons_path, exist_ok=True)

    target_addons = addon_filter if addon_filter is not None else list(game_addons.keys())

    for addon in target_addons:
        if addon not in game_addons:
            continue
        source = str(game_addons[addon]).strip()
        download_url = ""
        zip_name = ""

        try:
            if source.isnumeric():  # curseforge
                log_func(f"[{game_label}] getting latest version of {addon} from curseforge...")
                details = requests.get(f"https://www.curseforge.com/api/v1/mods/{source}/files")
                details.raise_for_status()
                files = details.json()
                addon_id = str(files["data"][0]["id"])
                file_name = files["data"][0]["fileName"]
                assert len(addon_id) == 7
                download_url = f"https://mediafilez.forgecdn.net/files/{addon_id[0:4]}/{addon_id[4:]}/{file_name}"
                zip_name = file_name
            else:
                owner, repo = parse_github_repo(source)
                response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
                response.raise_for_status()

                release_data = response.json()

                log_func(f"[{game_label}] getting download URL for {repo}")

                for asset in release_data.get("assets", []):
                    if asset.get("name", "").endswith(".zip"):
                        download_url = asset["browser_download_url"]
                        zip_name = asset["name"]
                        break

                if not download_url:
                    if prompt_source_func is not None:
                        use_source = prompt_source_func(addon)
                    else:
                        source_install = input(
                            f"could not get zip download from {addon}, "
                            f"try to install using source zip? y/n"
                        )
                        use_source = source_install.lower() in ["y", "yes"]

                    if use_source:
                        download_url = release_data["zipball_url"]
                        zip_name = f"{repo}.zip"
                    else:
                        continue

            log_func("downloading....")
            response = requests.get(download_url, stream=True)
            response.raise_for_status()

            with open(zip_name, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # Filter out keep-alive new chunks
                        f.write(chunk)
            log_func("download complete, installing....")
            if zip_name not in zip_names:
                zip_names.append(zip_name)
            with zipfile.ZipFile(zip_name, "r") as zippy:
                zippy.extractall(addons_path)
            log_func(f"successfully installed {zip_name} to {addons_path}")
        except Exception as exc:
            log_func(f"Failed to update {addon}: {exc}")

    return 0


def check_for_self_update(repo=None):
    """Check GitHub releases for a newer version of wow_addon_manager."""
    repo = repo or settings.get("self_update_repo", SELF_UPDATE_REPO)
    owner, repo_name = parse_github_repo(repo)
    response = requests.get(f"https://api.github.com/repos/{owner}/{repo_name}/releases/latest")
    response.raise_for_status()
    release_data = response.json()

    latest_version = str(release_data.get("tag_name") or release_data.get("name") or "")
    current_version = str(settings.get("version", DEFAULT_VERSION))

    download_url = ""
    asset_name = ""
    for asset in release_data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".zip"):
            download_url = asset.get("browser_download_url", "")
            asset_name = name
            break

    if not download_url and release_data.get("assets"):
        first_asset = release_data["assets"][0]
        download_url = first_asset.get("browser_download_url", "")
        asset_name = first_asset.get("name", "wow_addon_manager_update")

    if not download_url:
        download_url = release_data.get("zipball_url", "")
        asset_name = f"{repo_name}-{latest_version or 'latest'}.zip"

    update_available = bool(latest_version and latest_version != current_version)
    return {
        "update_available": update_available,
        "latest_version": latest_version,
        "current_version": current_version,
        "download_url": download_url,
        "asset_name": asset_name,
        "release_data": release_data,
    }


def _find_extracted_root(extract_dir):
    """If an archive extracts into a single top-level folder, return that folder."""
    entries = os.listdir(extract_dir)
    if len(entries) == 1:
        single_path = os.path.join(extract_dir, entries[0])
        if os.path.isdir(single_path):
            return single_path
    return extract_dir


def _launch_windows_updater_script(source_dir, app_dir, temp_dir, restart_exe=None):
    """Create and launch a detached batch script on Windows to replace locked PyInstaller files."""
    batch_path = os.path.join(temp_dir, "_wam_updater.bat")
    restart_cmd = f'start "" "{restart_exe}"\n' if restart_exe else ""
    batch_contents = (
        "@echo off\n"
        "timeout /t 2 /nobreak > NUL\n"
        f'xcopy /E /Y /I "{source_dir}\\*" "{app_dir}\\" > NUL\n'
        f"{restart_cmd}"
        f'rmdir /S /Q "{temp_dir}"\n'
        'del "%~f0"\n'
    )
    with open(batch_path, "w", encoding="utf-8") as bf:
        bf.write(batch_contents)

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", batch_path],
        creationflags=creationflags,
        close_fds=True,
    )


def self_update(
    force=False,
    log_func=print,
    confirm_func=None,
    target_dir=None,
    auto_exit_on_frozen=True,
):
    """
    Update the local install of wow_addon_manager from the latest GitHub release.
    Preserves local settings.json and addons.json.
    """
    log_func("Checking for wow_addon_manager updates on GitHub...")
    try:
        info = check_for_self_update()
    except Exception as exc:
        log_func(f"Failed to check for updates: {exc}")
        return 1

    latest_version = info["latest_version"]
    current_version = info["current_version"]
    download_url = info["download_url"]
    asset_name = info["asset_name"]

    if not download_url:
        log_func("No downloadable release artifact found.")
        return 1

    if not info["update_available"] and not force:
        log_func(f"You are already on the latest version ({current_version}).")
        if confirm_func is not None:
            proceed = confirm_func(
                f"Current version ({current_version}) matches latest release ({latest_version}). "
                f"Re-install anyway?"
            )
            if not proceed:
                return 0
        else:
            return 0
    else:
        if confirm_func is not None:
            proceed = confirm_func(
                f"Update wow_addon_manager from '{current_version}' to '{latest_version}'?"
            )
            if not proceed:
                log_func("Self-update cancelled.")
                return 0

    app_dir = target_dir or get_app_dir()
    temp_dir = tempfile.mkdtemp(prefix="wow_addon_manager_update_")
    archive_path = os.path.join(temp_dir, asset_name)

    try:
        log_func(f"Downloading update {latest_version} ({asset_name})...")
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        with open(archive_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        if zipfile.is_zipfile(archive_path):
            log_func("Extracting update package...")
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
            source_dir = _find_extracted_root(extract_dir)
        else:
            # Single binary/file asset
            source_dir = extract_dir
            shutil.copy2(archive_path, os.path.join(source_dir, asset_name))

        # Preserve user configuration files (do not overwrite settings.json or addons.json)
        for config_file in ("settings.json", "addons.json"):
            staged_config = os.path.join(source_dir, config_file)
            if os.path.exists(staged_config):
                os.remove(staged_config)

        # Save new version into settings
        if latest_version:
            settings["version"] = latest_version
        save_settings(os.path.join(app_dir, "settings.json"))
        save_addons(os.path.join(app_dir, "addons.json"))

        is_frozen_windows = getattr(sys, "frozen", False) and os.name == "nt" and target_dir is None
        if is_frozen_windows:
            log_func("Applying update via background updater and restarting...")
            _launch_windows_updater_script(
                source_dir=source_dir,
                app_dir=app_dir,
                temp_dir=temp_dir,
                restart_exe=sys.executable,
            )
            if auto_exit_on_frozen:
                sys.exit(0)
            return 0

        log_func(f"Installing updated files to {app_dir}...")
        shutil.copytree(source_dir, app_dir, dirs_exist_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        log_func(f"Successfully updated wow_addon_manager to version {latest_version}!")
        return 0
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        log_func(f"Self-update failed: {exc}")
        return 1


def cleanup_downloaded_zips(log_func=print):
    """Remove downloaded addon zip files tracked in zip_names."""
    removed = []
    for name in list(zip_names):
        if os.path.exists(name):
            try:
                os.remove(name)
                removed.append(name)
            except OSError as exc:
                log_func(f"Could not remove {name}: {exc}")
        zip_names.remove(name)
    if removed:
        log_func(f"Removed {len(removed)} downloaded zip file(s).")
    return removed


# ---------------------------------------------------------------------------
# CLI Functions
# ---------------------------------------------------------------------------

def main_menu():
    """display the main menu"""
    current_game_label = GAME_LABELS.get(get_active_game(), "World of Warcraft")
    user_input = input(
        f"welcome to the wow addon manager by tshinhar (Active game: {current_game_label})\n"
        "please choose what you want to do:\n"
        "1) update - update addons\n"
        "2) add - add addon\n"
        "3) settings - edit setting\n"
        "4) remove - remove addons\n"
        "5) switch - switch game (World of Warcraft / World of Warcraft Forever)\n"
        "6) self-update - update wow_addon_manager from GitHub release\n"
        "7) ui - open graphical interface\n"
        "8) exit - exit\n"
    )
    return user_input.strip()


def switch_game_cli():
    """Switch active game between World of Warcraft and World of Warcraft Forever."""
    print("Select game:")
    print("1) World of Warcraft")
    print("2) World of Warcraft Forever")
    choice = input("Enter choice (1/2): ").strip().lower()
    if choice in ["1", "wow", "world of warcraft"]:
        set_active_game(GAME_WOW)
        print(f"Switched active game to {GAME_LABELS[GAME_WOW]}")
        return 0
    if choice in ["2", "wow_forever", "forever", "world of warcraft forever"]:
        set_active_game(GAME_WOW_FOREVER)
        print(f"Switched active game to {GAME_LABELS[GAME_WOW_FOREVER]}")
        return 0
    print("Invalid game choice.")
    return 1


def edit_settings():
    """Edit a setting in settings.json."""
    print(f"current settings:\n{settings}")
    setting_name = input("what setting do you want to change?").strip()
    if setting_name not in settings:
        print("this setting dose not exist, check your spelling!")
        return 1
    value = input("insert new value for the setting")
    settings[setting_name] = value
    return 0


def add_addon(game=None):
    """Add an addon to the selected game's addon list."""
    game = game or get_active_game()
    game_addons = get_game_addons(game)
    print(f"current addons ({GAME_LABELS.get(game, game)}):\n{game_addons}")
    new_name = input("give a name to the new addon:").strip()
    url = input("insert the repo url of the addon (github) or the addon id (curseforge)").strip()
    confirm = input(f"add {new_name} with URL/ID {url}? y/n")
    if confirm.lower() in ["y", "yes"]:
        game_addons[new_name] = url
        return 0
    return 1


def remove(game=None):
    """Remove installed addon folders and optionally their repository entries."""
    game = game or get_active_game()
    path = get_game_addons_path(game)
    game_addons = get_game_addons(game)
    if not path or not os.path.isdir(path):
        print(f"Addons path '{path}' does not exist.")
        return 1
    installed_addons = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
    print(f"current addons:\n{installed_addons}")
    addon_names = input(
        "which addon/s you wish to remove? list the ones you want to remove separated by ','"
        "or use 'all' to remove everything"
    )
    confirm = input(f"{addon_names} will be removed please confirm? y/n")
    if confirm.lower() in ["y", "yes"]:
        if addon_names.strip() == "all":
            targets = list(installed_addons)
        else:
            targets = [a.strip() for a in addon_names.split(",") if a.strip()]
        for addon_name in targets:
            print(f"removing {addon_name}...")
            target_dir = os.path.join(path, addon_name)
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            if addon_name in game_addons:
                remove_repo = input(f"do you also want to remove the repo for {addon_name}? y/n")
                if remove_repo.lower() in ["yes", "y"]:
                    del game_addons[addon_name]
        return 0
    return 1


def run_cli():
    """Run the interactive command-line interface."""
    load_settings()
    load_addons()
    while True:
        option = main_menu().lower()
        if option in ["8", "exit", "quit"]:
            break
        if option in ["1", "update"]:
            update()
        elif option in ["2", "add"]:
            add_addon()
        elif option in ["3", "settings"]:
            edit_settings()
        elif option in ["4", "remove"]:
            remove()
        elif option in ["5", "switch"]:
            switch_game_cli()
        elif option in ["6", "self-update", "self_update"]:
            self_update(
                confirm_func=lambda msg: input(f"{msg} y/n: ").strip().lower() in ["y", "yes"]
            )
        elif option in ["7", "ui", "gui"]:
            save_settings()
            save_addons()
            launch_ui()
            break

    save_settings()
    save_addons()

    if zip_names:
        cleanup = input("remove downloaded zip files before exiting? y/n")
        if cleanup.lower() in ["y", "yes"]:
            print("removing....")
            cleanup_downloaded_zips()
    print("by by")


# ---------------------------------------------------------------------------
# Graphical User Interface (Tkinter)
# ---------------------------------------------------------------------------

class AddonManagerUI:
    """Basic Tkinter GUI for WoW Addon Manager."""

    def __init__(self, root):
        self.root = root
        self.root.title("WoW Addon Manager")
        self.root.geometry("860x640")
        self.root.minsize(720, 520)

        load_settings()
        load_addons()

        self.game_var = tk.StringVar(value=get_active_game())
        self.path_var = tk.StringVar(value=get_game_addons_path())
        self.auto_cleanup_var = tk.BooleanVar(value=True)
        self.version_var = tk.StringVar(value=f"v{settings.get('version', DEFAULT_VERSION)}")
        self._busy = False

        self._build_ui()
        self.refresh_all()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        # Top header bar: Title + Version + Self-Update button
        header_frame = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        header_frame.pack(fill=tk.X)

        title_lbl = ttk.Label(
            header_frame,
            text="WoW Addon Manager",
            font=("TkDefaultFont", 14, "bold"),
        )
        title_lbl.pack(side=tk.LEFT)

        version_lbl = ttk.Label(
            header_frame,
            textvariable=self.version_var,
            font=("TkDefaultFont", 10),
        )
        version_lbl.pack(side=tk.LEFT, padx=(8, 0))

        self.self_update_btn = ttk.Button(
            header_frame,
            text="Self Update (GitHub Release)",
            command=self.on_self_update,
        )
        self.self_update_btn.pack(side=tk.RIGHT)

        self.settings_btn = ttk.Button(
            header_frame,
            text="Settings...",
            command=self.open_settings_dialog,
        )
        self.settings_btn.pack(side=tk.RIGHT, padx=(0, 8))

        # Game Selection & Install Location Frame
        config_frame = ttk.LabelFrame(
            self.root,
            text="Game Profile & Addons Location",
            padding=(12, 8),
        )
        config_frame.pack(fill=tk.X, padx=12, pady=(4, 8))

        game_row = ttk.Frame(config_frame)
        game_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(game_row, text="Select Game:", font=("TkDefaultFont", 10, "bold")).pack(
            side=tk.LEFT, padx=(0, 12)
        )

        ttk.Radiobutton(
            game_row,
            text=GAME_LABELS[GAME_WOW],
            variable=self.game_var,
            value=GAME_WOW,
            command=self.on_game_changed,
        ).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Radiobutton(
            game_row,
            text=GAME_LABELS[GAME_WOW_FOREVER],
            variable=self.game_var,
            value=GAME_WOW_FOREVER,
            command=self.on_game_changed,
        ).pack(side=tk.LEFT)

        path_row = ttk.Frame(config_frame)
        path_row.pack(fill=tk.X)

        ttk.Label(path_row, text="Addons Path:").pack(side=tk.LEFT, padx=(0, 8))

        self.path_entry = ttk.Entry(path_row, textvariable=self.path_var)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        ttk.Button(path_row, text="Browse...", command=self.browse_path).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(path_row, text="Save Path", command=self.save_current_path).pack(
            side=tk.LEFT
        )

        # Middle area: PanedWindow with Tracked Addons (left) and Installed Folders on disk (right)
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        # Left pane: Tracked Addons
        tracked_frame = ttk.LabelFrame(paned, text="Tracked Addons (addons.json)", padding=8)
        paned.add(tracked_frame, weight=3)

        columns = ("name", "source", "type")
        self.addons_tree = ttk.Treeview(
            tracked_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=10,
        )
        self.addons_tree.heading("name", text="Addon Name")
        self.addons_tree.heading("source", text="GitHub URL / CurseForge ID")
        self.addons_tree.heading("type", text="Source Type")

        self.addons_tree.column("name", width=150, anchor=tk.W)
        self.addons_tree.column("source", width=270, anchor=tk.W)
        self.addons_tree.column("type", width=90, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(
            tracked_frame, orient=tk.VERTICAL, command=self.addons_tree.yview
        )
        self.addons_tree.configure(yscrollcommand=tree_scroll.set)

        self.addons_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right pane: Installed folders in addons_path
        installed_frame = ttk.LabelFrame(
            paned, text="Installed Folders on Disk", padding=8
        )
        paned.add(installed_frame, weight=2)

        self.installed_listbox = tk.Listbox(
            installed_frame, selectmode=tk.EXTENDED, height=10
        )
        inst_scroll = ttk.Scrollbar(
            installed_frame, orient=tk.VERTICAL, command=self.installed_listbox.yview
        )
        self.installed_listbox.configure(yscrollcommand=inst_scroll.set)

        self.installed_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inst_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Action Buttons Frame
        actions_frame = ttk.Frame(self.root, padding=(12, 6))
        actions_frame.pack(fill=tk.X)

        self.update_all_btn = ttk.Button(
            actions_frame,
            text="Update All Addons",
            command=self.on_update_all,
        )
        self.update_all_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.update_sel_btn = ttk.Button(
            actions_frame,
            text="Update Selected",
            command=self.on_update_selected,
        )
        self.update_sel_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.add_btn = ttk.Button(
            actions_frame,
            text="Add Addon...",
            command=self.on_add_addon,
        )
        self.add_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.remove_tracked_btn = ttk.Button(
            actions_frame,
            text="Remove Tracked Addon",
            command=self.on_remove_tracked,
        )
        self.remove_tracked_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.remove_disk_btn = ttk.Button(
            actions_frame,
            text="Delete Selected Folder(s)",
            command=self.on_remove_installed_folders,
        )
        self.remove_disk_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            actions_frame,
            text="Refresh",
            command=self.refresh_all,
        ).pack(side=tk.RIGHT)

        ttk.Checkbutton(
            actions_frame,
            text="Clean up zips after update",
            variable=self.auto_cleanup_var,
        ).pack(side=tk.RIGHT, padx=(0, 10))

        # Status / Log Output Frame
        log_frame = ttk.LabelFrame(self.root, text="Activity Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=False, padx=12, pady=(2, 10))

        self.log_text = ScrolledText(log_frame, height=8, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, message):
        """Append a message to the activity log in a thread-safe manner."""
        def _append():
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, str(message) + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.root.after(0, _append)

    def _set_busy(self, busy):
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL

        def _update_buttons():
            for btn in (
                self.update_all_btn,
                self.update_sel_btn,
                self.add_btn,
                self.remove_tracked_btn,
                self.remove_disk_btn,
                self.self_update_btn,
            ):
                btn.configure(state=state)

        self.root.after(0, _update_buttons)

    def _ask_yes_no_threadsafe(self, title, question):
        """Show a yes/no messagebox from a worker thread and wait for the user's response."""
        result_holder = {"value": False}
        event = threading.Event()

        def _ask():
            result_holder["value"] = messagebox.askyesno(title, question, parent=self.root)
            event.set()

        self.root.after(0, _ask)
        event.wait()
        return result_holder["value"]

    def on_game_changed(self):
        game = self.game_var.get()
        set_active_game(game)
        save_settings()
        self.path_var.set(get_game_addons_path(game))
        self.refresh_all()
        self.log(f"Switched active game to {GAME_LABELS.get(game, game)}.")

    def browse_path(self):
        initial = self.path_var.get() or get_app_dir()
        chosen = filedialog.askdirectory(
            parent=self.root,
            title=f"Select Addons Folder for {GAME_LABELS.get(self.game_var.get())}",
            initialdir=initial if os.path.isdir(initial) else get_app_dir(),
        )
        if chosen:
            self.path_var.set(chosen)
            self.save_current_path()

    def save_current_path(self):
        game = self.game_var.get()
        new_path = self.path_var.get().strip()
        set_game_addons_path(new_path, game)
        save_settings()
        self.refresh_installed_list()
        self.log(f"Saved addons path for {GAME_LABELS.get(game)}: {new_path}")

    def refresh_all(self):
        self.version_var.set(f"v{settings.get('version', DEFAULT_VERSION)}")
        self.path_var.set(get_game_addons_path(self.game_var.get()))
        self.refresh_tracked_list()
        self.refresh_installed_list()

    def refresh_tracked_list(self):
        for item in self.addons_tree.get_children():
            self.addons_tree.delete(item)
        game_addons = get_game_addons(self.game_var.get())
        for name, source in game_addons.items():
            src_str = str(source).strip()
            src_type = "CurseForge" if src_str.isnumeric() else "GitHub"
            self.addons_tree.insert("", tk.END, iid=name, values=(name, src_str, src_type))

    def refresh_installed_list(self):
        self.installed_listbox.delete(0, tk.END)
        for folder in get_installed_addon_dirs(self.game_var.get()):
            self.installed_listbox.insert(tk.END, folder)

    def on_add_addon(self):
        game = self.game_var.get()
        game_label = GAME_LABELS.get(game, game)

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Add Addon - {game_label}")
        dialog.geometry("460x180")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Addon Name:").grid(row=0, column=0, sticky=tk.W, pady=6)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(frame, textvariable=name_var, width=42)
        name_entry.grid(row=0, column=1, sticky=tk.EW, padx=(8, 0), pady=6)

        ttk.Label(frame, text="GitHub URL or CurseForge ID:").grid(
            row=1, column=0, sticky=tk.W, pady=6
        )
        url_var = tk.StringVar()
        url_entry = ttk.Entry(frame, textvariable=url_var, width=42)
        url_entry.grid(row=1, column=1, sticky=tk.EW, padx=(8, 0), pady=6)

        frame.columnconfigure(1, weight=1)

        def _submit():
            name = name_var.get().strip()
            url = url_var.get().strip()
            if not name or not url:
                messagebox.showwarning(
                    "Missing Input",
                    "Please enter both an addon name and a GitHub URL or CurseForge ID.",
                    parent=dialog,
                )
                return
            game_addons = get_game_addons(game)
            game_addons[name] = url
            save_addons()
            self.refresh_tracked_list()
            self.log(f"[{game_label}] Added addon '{name}' -> {url}")
            dialog.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky=tk.E, pady=(14, 0))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="Add Addon", command=_submit).pack(side=tk.RIGHT)
        name_entry.focus_set()

    def on_remove_tracked(self):
        selected = self.addons_tree.selection()
        if not selected:
            messagebox.showinfo(
                "No Selection",
                "Please select one or more tracked addons to remove.",
                parent=self.root,
            )
            return

        game = self.game_var.get()
        game_label = GAME_LABELS.get(game, game)
        names_str = ", ".join(selected)
        if not messagebox.askyesno(
            "Confirm Removal",
            f"Remove tracked addon(s) [{names_str}] from {game_label}?",
            parent=self.root,
        ):
            return

        addons_path = get_game_addons_path(game)
        game_addons = get_game_addons(game)

        for addon_name in selected:
            if addon_name in game_addons:
                del game_addons[addon_name]
                self.log(f"[{game_label}] Removed '{addon_name}' from tracked addons.")

            if addons_path and os.path.isdir(os.path.join(addons_path, addon_name)):
                if messagebox.askyesno(
                    "Delete Installed Folder",
                    f"Also delete installed folder '{addon_name}' from disk?",
                    parent=self.root,
                ):
                    shutil.rmtree(os.path.join(addons_path, addon_name), ignore_errors=True)
                    self.log(f"[{game_label}] Deleted folder '{addon_name}' from disk.")

        save_addons()
        self.refresh_all()

    def on_remove_installed_folders(self):
        indices = self.installed_listbox.curselection()
        if not indices:
            messagebox.showinfo(
                "No Selection",
                "Please select one or more installed folders on disk to delete.",
                parent=self.root,
            )
            return

        folders = [self.installed_listbox.get(i) for i in indices]
        game = self.game_var.get()
        addons_path = get_game_addons_path(game)
        game_addons = get_game_addons(game)

        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete {len(folders)} folder(s) from {addons_path}?\n\n{', '.join(folders)}",
            parent=self.root,
        ):
            return

        for folder in folders:
            target = os.path.join(addons_path, folder)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
                self.log(f"Deleted installed folder: {folder}")
            if folder in game_addons:
                if messagebox.askyesno(
                    "Remove Tracked Repo",
                    f"Do you also want to remove the tracked entry for '{folder}'?",
                    parent=self.root,
                ):
                    del game_addons[folder]
                    self.log(f"Removed '{folder}' from tracked addons.")

        save_addons()
        self.refresh_all()

    def _run_update_worker(self, game, addon_filter=None):
        self._set_busy(True)
        try:
            update(
                game=game,
                addon_filter=addon_filter,
                log_func=self.log,
                prompt_source_func=lambda addon: self._ask_yes_no_threadsafe(
                    "Source Zip Fallback",
                    f"Could not get release zip download from '{addon}'.\n"
                    f"Try to install using source zip instead?",
                ),
            )
            if self.auto_cleanup_var.get() and zip_names:
                cleanup_downloaded_zips(log_func=self.log)
        finally:
            self.root.after(0, self.refresh_all)
            self._set_busy(False)

    def on_update_all(self):
        if self._busy:
            return
        self.save_current_path()
        game = self.game_var.get()
        threading.Thread(
            target=self._run_update_worker, args=(game, None), daemon=True
        ).start()

    def on_update_selected(self):
        if self._busy:
            return
        selected = list(self.addons_tree.selection())
        if not selected:
            messagebox.showinfo(
                "No Selection",
                "Select one or more tracked addons to update, or click 'Update All Addons'.",
                parent=self.root,
            )
            return
        self.save_current_path()
        game = self.game_var.get()
        threading.Thread(
            target=self._run_update_worker, args=(game, selected), daemon=True
        ).start()

    def on_self_update(self):
        if self._busy:
            return

        def _worker():
            self._set_busy(True)
            try:
                rc = self_update(
                    log_func=self.log,
                    confirm_func=lambda msg: self._ask_yes_no_threadsafe("Self Update", msg),
                    auto_exit_on_frozen=False,
                )
                self.root.after(0, self.refresh_all)
                if rc == 0 and getattr(sys, "frozen", False) and os.name == "nt":
                    self.root.after(0, self.root.destroy)
            finally:
                self._set_busy(False)

        threading.Thread(target=_worker, daemon=True).start()

    def open_settings_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("540x230")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        wow_path_var = tk.StringVar(value=settings.get("addons_path", ""))
        forever_path_var = tk.StringVar(value=settings.get("wow_forever_addons_path", ""))

        ttk.Label(frame, text="World of Warcraft Addons Path:").grid(
            row=0, column=0, sticky=tk.W, pady=6
        )
        ttk.Entry(frame, textvariable=wow_path_var, width=40).grid(
            row=0, column=1, sticky=tk.EW, padx=6, pady=6
        )
        ttk.Button(
            frame,
            text="Browse...",
            command=lambda: self._browse_into_var(wow_path_var, dialog),
        ).grid(row=0, column=2, pady=6)

        ttk.Label(frame, text="WoW Forever Addons Path:").grid(
            row=1, column=0, sticky=tk.W, pady=6
        )
        ttk.Entry(frame, textvariable=forever_path_var, width=40).grid(
            row=1, column=1, sticky=tk.EW, padx=6, pady=6
        )
        ttk.Button(
            frame,
            text="Browse...",
            command=lambda: self._browse_into_var(forever_path_var, dialog),
        ).grid(row=1, column=2, pady=6)

        ttk.Label(frame, text="Current Version:").grid(
            row=2, column=0, sticky=tk.W, pady=6
        )
        ttk.Label(frame, text=str(settings.get("version", DEFAULT_VERSION))).grid(
            row=2, column=1, sticky=tk.W, padx=6, pady=6
        )

        frame.columnconfigure(1, weight=1)

        def _save():
            settings["addons_path"] = wow_path_var.get().strip()
            settings["wow_forever_addons_path"] = forever_path_var.get().strip()
            save_settings()
            self.refresh_all()
            self.log("Settings updated.")
            dialog.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky=tk.E, pady=(16, 0))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="Save Settings", command=_save).pack(side=tk.RIGHT)

    def _browse_into_var(self, target_var, parent):
        chosen = filedialog.askdirectory(parent=parent, initialdir=target_var.get() or get_app_dir())
        if chosen:
            target_var.set(chosen)

    def on_close(self):
        save_settings()
        save_addons()
        if self.auto_cleanup_var.get() and zip_names:
            cleanup_downloaded_zips(log_func=lambda _: None)
        self.root.destroy()


def launch_ui():
    """Launch the Tkinter graphical user interface."""
    if not TK_AVAILABLE:
        print("Tkinter is not available on this system. Falling back to CLI.")
        run_cli()
        return
    root = tk.Tk()
    AddonManagerUI(root)
    root.mainloop()


if __name__ == "__main__":
    load_settings()
    load_addons()
    if "--cli" in sys.argv:
        run_cli()
    else:
        try:
            launch_ui()
        except tk.TclError:
            # Fallback to CLI if no display server is available
            run_cli()
