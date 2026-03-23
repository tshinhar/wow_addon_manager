"""
WoW Addon Manager - A simple tool for managing World of Warcraft addons.
"""
import json
import requests
import os
import zipfile
import shutil
import sys
import itertools
import threading

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def validate_addon_name(name: str) -> bool:
    if not name or ".." in name or name.startswith("/"):
        return False
    return True


def parse_github_url(url: str) -> tuple[str, str]:
    cleaned = url.replace("https://github.com/", "").replace("http://github.com/", "")
    parts = cleaned.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid GitHub URL format: {url}")
    return parts[0], parts[1]


def spinner(message: str, stop_event: threading.Event):
    symbols = itertools.cycle(['|', '/', '-', '\\'])
    while not stop_event.is_set():
        sys.stdout.write(f'\r{CYAN}{next(symbols)}{RESET} {message}')
        sys.stdout.flush()
        stop_event.wait(0.1)
    sys.stdout.write('\r' + ' ' * (len(message) + 2) + '\r')
    sys.stdout.flush()


class DownloadProgressBar:
    def __init__(self, total: int = 0):
        self.total = total
        self.current = 0

    def update(self, chunk_size: int):
        self.current += chunk_size
        if self.total > 0:
            percent = min(100, int(self.current * 100 / self.total))
            bar_len = 30
            filled = int(bar_len * percent / 100)
            bar = '=' * filled + '>' + ' ' * (bar_len - filled - 1)
            size_mb = self.current / (1024 * 1024)
            total_mb = self.total / (1024 * 1024)
            sys.stdout.write(f'\r{CYAN}[{bar}]{RESET} {percent}% {size_mb:.1f}MB/{total_mb:.1f}MB')
        else:
            size_mb = self.current / (1024 * 1024)
            sys.stdout.write(f'\r{CYAN}{size_mb:.1f}MB downloaded{RESET}')
        sys.stdout.flush()

    def finish(self):
        sys.stdout.write('\r' + ' ' * 60 + '\r')
        sys.stdout.flush()


def print_header():
    print(f"{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════╗")
    print("  ║     WoW Addon Manager by tshinhar    ║")
    print("  ╚══════════════════════════════════════╝")
    print(f"{RESET}")


def main_menu():
    print_header()
    print(f"{BOLD}Main Menu:{RESET}")
    print(f"  {GREEN}1){RESET} Update addons")
    print(f"  {GREEN}2){RESET} Add addon")
    print(f"  {GREEN}3){RESET} Edit settings")
    print(f"  {GREEN}4){RESET} Remove addons")
    print(f"  {RED}5){RESET} Exit")
    print()

    while True:
        choice = input(f"{YELLOW}Choose an option (1-5): {RESET}").strip()
        if choice in ["1", "2", "3", "4", "5", "update", "add", "settings", "remove", "exit"]:
            return choice
        print(f"{RED}Invalid choice. Please enter 1-5 or a command name.{RESET}")


def edit_settings():
    print(f"\n{BOLD}Current Settings:{RESET}")
    for key, value in settings.items():
        print(f"  {CYAN}{key}{RESET}: {value}")
    print()

    setting_name = input(f"{YELLOW}What setting do you want to change? {RESET}").strip()
    if setting_name not in settings:
        print(f"{RED}Error: Setting '{setting_name}' does not exist.{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    print(f"Current value: {settings[setting_name]}")
    value = input(f"{YELLOW}Enter new value: {RESET}").strip()

    while not value:
        print(f"{RED}Value cannot be empty.{RESET}")
        value = input(f"{YELLOW}Enter new value: {RESET}").strip()

    settings[setting_name] = value
    print(f"{GREEN}Setting updated successfully!{RESET}")
    input(f"{YELLOW}Press Enter to continue...{RESET}")


def add_addon():
    print(f"\n{BOLD}Current Addons:{RESET}")
    if addons:
        for name, url in addons.items():
            print(f"  {CYAN}{name}{RESET}: {url}")
    else:
        print(f"  {YELLOW}No addons configured.{RESET}")
    print()

    new_name = input(f"{YELLOW}Enter a name for the new addon: {RESET}").strip()
    if not new_name:
        print(f"{RED}Error: Name cannot be empty.{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    url = input(f"{YELLOW}Enter repo URL (GitHub) or ID (CurseForge): {RESET}").strip()
    if not url:
        print(f"{RED}Error: URL/ID cannot be empty.{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    print(f"\n{GREEN}Add {CYAN}{new_name}{GREEN} with URL/ID:{RESET}")
    print(f"  {url}")
    confirm = input(f"{YELLOW}Confirm? (y/n): {RESET}").strip().lower()

    if confirm in ["y", "yes"]:
        addons[new_name] = url
        print(f"{GREEN}Addon added successfully!{RESET}")
    else:
        print(f"{YELLOW}Cancelled.{RESET}")

    input(f"{YELLOW}Press Enter to continue...{RESET}")


def update():
    print(f"\n{BOLD}Updating Addons...{RESET}\n")

    if not addons:
        print(f"{YELLOW}No addons to update. Add some first!{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    success_count = 0
    fail_count = 0

    for addon in addons:
        download_url = ""
        zip_name = ""
        download_url_api = ""
        download_size = 0

        try:
            if addons[addon].isnumeric():
                print(f"{CYAN}Fetching CurseForge info for {addon}...{RESET}")
                stop_event = threading.Event()
                t = threading.Thread(target=spinner, args=("Checking CurseForge...", stop_event))
                t.start()

                details = requests.get(
                    f"https://www.curseforge.com/api/v1/mods/{addons[addon]}/files",
                    timeout=30
                )
                stop_event.set()
                t.join()
                details.raise_for_status()

                files = details.json()
                addon_id = str(files["data"][0]["id"])
                file_name = files["data"][0]["fileName"]

                if len(addon_id) < 7:
                    raise ValueError(f"Unexpected CurseForge file ID format: {addon_id}")

                download_url = f"https://mediafilez.forgecdn.net/files/{addon_id[0:4]}/{addon_id[4:]}/{file_name}"
                zip_name = file_name
            else:
                owner, repo = parse_github_url(addons[addon])
                print(f"{CYAN}Fetching GitHub release for {repo}...{RESET}")

                stop_event = threading.Event()
                t = threading.Thread(target=spinner, args=("Checking GitHub...", stop_event))
                t.start()

                response = requests.get(
                    f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                    timeout=30
                )
                stop_event.set()
                t.join()
                response.raise_for_status()

                release_data = response.json()

                for asset in release_data["assets"]:
                    if asset["name"].endswith(".zip"):
                        download_url = asset["browser_download_url"]
                        zip_name = asset["name"]
                        download_size = asset.get("size", 0)
                        break

                if not download_url:
                    print(f"{YELLOW}No zip found for {addon}.{RESET}")
                    source_install = input(f"Try source zip? (y/n): ").strip().lower()
                    if source_install in ["y", "yes"]:
                        download_url = release_data["zipball_url"]
                        zip_name = f"{repo}.zip"
                    else:
                        fail_count += 1
                        continue

            print(f"{CYAN}Downloading {zip_name}...{RESET}")
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()

            content_length = response.headers.get('content-length')
            if content_length:
                download_size = int(content_length)

            progress = DownloadProgressBar(download_size)

            with open(zip_name, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        progress.update(len(chunk))

            progress.finish()
            print(f"{GREEN}Download complete!{RESET}")

            zip_names.append(zip_name)
            with zipfile.ZipFile(zip_name, 'r') as zippy:
                zippy.extractall(settings["addons_path"])

            print(f"{GREEN}✓ Successfully installed {addon}{RESET}\n")
            success_count += 1

        except requests.exceptions.Timeout:
            print(f"{RED}✗ Request timed out for {addon}{RESET}\n")
            fail_count += 1
        except requests.exceptions.RequestException as e:
            print(f"{RED}✗ Failed to download {addon}: {e}{RESET}\n")
            fail_count += 1
        except (zipfile.BadZipFile, IOError) as e:
            print(f"{RED}✗ Failed to extract {addon}: {e}{RESET}\n")
            fail_count += 1
        except ValueError as e:
            print(f"{RED}✗ {addon}: {e}{RESET}\n")
            fail_count += 1

    print(f"\n{BOLD}Update Summary:{RESET}")
    print(f"  {GREEN}✓ Success: {success_count}{RESET}")
    print(f"  {RED}✗ Failed:  {fail_count}{RESET}")
    input(f"{YELLOW}Press Enter to continue...{RESET}")


def remove():
    print(f"\n{BOLD}Remove Addons{RESET}\n")

    path = settings["addons_path"]
    try:
        installed_addons = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
    except OSError as e:
        print(f"{RED}Error: Could not read addons directory: {e}{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    if not installed_addons:
        print(f"{YELLOW}No addons installed.{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    print(f"{BOLD}Installed Addons:{RESET}")
    for addon in installed_addons:
        print(f"  {CYAN}{addon}{RESET}")
    print()

    addon_names = input(f"{YELLOW}Enter addon names separated by ',' (or 'all'): {RESET}").strip()
    if not addon_names:
        print(f"{RED}Error: No addon specified.{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    if addon_names == "all":
        addon_names = ",".join(installed_addons)

    print(f"\n{YELLOW}The following will be removed:{RESET}")
    for name in addon_names.split(","):
        print(f"  {RED}{name.strip()}{RESET}")

    confirm = input(f"\n{YELLOW}Confirm removal? (y/n): {RESET}").strip().lower()
    if confirm not in ["y", "yes"]:
        print(f"{YELLOW}Cancelled.{RESET}")
        input(f"{YELLOW}Press Enter to continue...{RESET}")
        return

    removed_count = 0
    for addon_name in addon_names.split(","):
        addon_name = addon_name.strip()
        if not validate_addon_name(addon_name):
            print(f"{RED}Invalid addon name: {addon_name}{RESET}")
            continue
        if addon_name not in installed_addons:
            print(f"{RED}Addon not found: {addon_name}{RESET}")
            continue

        try:
            shutil.rmtree(os.path.join(path, addon_name))
            print(f"{GREEN}✓ Removed {addon_name}{RESET}")
            removed_count += 1
        except OSError as e:
            print(f"{RED}✗ Could not remove {addon_name}: {e}{RESET}")
            continue

        remove_repo = input(f"Remove from tracking list? (y/n): ").strip().lower()
        if remove_repo in ["yes", "y"]:
            if addon_name in addons:
                del addons[addon_name]
                print(f"{GREEN}  Removed from tracking.{RESET}")

    print(f"\n{GREEN}Removed {removed_count} addon(s).{RESET}")
    input(f"{YELLOW}Press Enter to continue...{RESET}")


if __name__ == '__main__':
    try:
        with open("settings.json") as sf:
            settings = json.load(sf)
        with open("addons.json") as af:
            addons = json.load(af)
    except FileNotFoundError as e:
        print(f"{RED}Error: Required file not found: {e}{RESET}")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"{RED}Error: Invalid JSON format: {e}{RESET}")
        exit(1)

    zip_names = []

    while True:
        clear_screen()
        option = main_menu()

        if option in ["5", "exit"]:
            break

        clear_screen()

        if option in ["1", "update"]:
            update()
        elif option in ["2", "add"]:
            add_addon()
        elif option in ["3", "settings"]:
            edit_settings()
        elif option in ["4", "remove"]:
            remove()

    clear_screen()
    print(f"\n{BOLD}Saving changes...{RESET}\n")

    try:
        with open("settings.json", "w") as sfile:
            json.dump(settings, sfile, indent=2)
        with open("addons.json", "w") as afile:
            json.dump(addons, afile, indent=2)
        print(f"{GREEN}✓ Settings saved.{RESET}")
    except IOError as e:
        print(f"{RED}✗ Failed to save settings: {e}{RESET}")

    if zip_names:
        cleanup = input(f"\n{YELLOW}Remove downloaded zip files? (y/n): {RESET}").strip().lower()
        if cleanup in ["y", "yes"]:
            print(f"\n{CYAN}Cleaning up...{RESET}")
            for name in zip_names:
                try:
                    os.remove(name)
                except OSError as e:
                    print(f"{YELLOW}Could not remove {name}: {e}{RESET}")

    print(f"\n{GREEN}{BOLD}Goodbye!{RESET}\n")
