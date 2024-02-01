"""
this is the main section of the wow addon manager
created by tshinhar
"""
import json
import requests
import os
import zipfile
import shutil


def main_menu():
    """display the main manu"""
    user_input = input("welcome to the wow addon manager by tshinhar\n"
                       "please choose what you want to do:\n"
                       "1) update - update addons\n"
                       "2) add - add addon\n"
                       "3) settings - edit setting\n"
                       "4) remove - remove addons\n"
                       "5) exit - exit\n")
    return user_input


def edit_settings():
    """add an addon"""
    print(f"current addons:\n{settings}")
    setting_name = input("what setting do you want to change?")
    if setting_name not in settings:
        print("this setting dose not exist, check your spelling!")
        return 1
    value = input("insert new value for the setting")
    settings[setting_name] = value
    return 0


def add_addon():
    """add an addon"""
    print(f"current addons:\n{addons}")
    new_name = input("give a name to the new addon:")
    url = input("insert the repo url of the addon (github) or the addon id (curseforge)")
    confirm = input(f"add {new_name} with URL/ID {url}? y/n")
    if confirm.lower() in ["y", "yes"]:
        addons[new_name] = url
        return 0


def update():
    """update all currently listed addons to latest version"""
    for addon in addons:
        download_url = ""
        zip_name = ""
        if addons[addon].isnumeric(): # curseforge
            print("getting latest version from curseforge...")
            details = requests.get(f"https://www.curseforge.com/api/v1/mods/{addons[addon]}/files")
            details.raise_for_status()
            files = details.json()
            addon_id = str(files["data"][0]["id"])
            file_name = files["data"][0]["fileName"]
            assert len(addon_id) == 7
            download_url = f"https://mediafilez.forgecdn.net/files/{addon_id[0:4]}/{addon_id[4:]}/{file_name}"
            zip_name = file_name
        else:
            owner, repo = addons[addon].replace("https://github.com/", "").split("/")
            response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
            response.raise_for_status()

            release_data = response.json()

            print(f"getting downlaod URL for {repo}")

            for asset in release_data["assets"]:
                if asset["name"].endswith(".zip"):
                    download_url = asset["browser_download_url"]
                    zip_name = asset["name"]
                    break
            if not download_url:
                source_install = input(f"could not get zip download from {addon}, "
                                    f"try to install using source zip? y/n")
                if source_install.lower() in ["y", "yes"]:
                    download_url = release_data["zipball_url"]
                    zip_name = f"{repo}.zip"
                else:
                    continue
        print("downloading....")
        response = requests.get(download_url, stream=True)
        response.raise_for_status()

        with open(zip_name, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # Filter out keep-alive new chunks
                    f.write(chunk)
        print("download complete, installing....")
        zip_names.append(zip_name)
        with zipfile.ZipFile(zip_name, 'r') as zippy:
            zippy.extractall(settings["addons_path"])
        print(f"successfully installed {zip_name}")


def remove():
    """removes an addon"""
    path = settings["addons_path"]
    installed_addons = [d for d in os.listdir(settings["addons_path"]) if os.path.isdir(os.path.join(path, d))]
    print(f"current addons:\n{installed_addons}")
    addon_names = input("which addon/s you wish to remove? list the ones you want to remove separated by ','"
                        "or use 'all' to remove everything")
    confirm = input(f"{addon_names} will be removed please confirm? y/n")
    if confirm.lower() in ["y", "yes"]:
        if addon_names == "all":
            addon_names = installed_addons
        for addon_name in addon_names.split(","):
            print(f"removing {addon_name}...")
            shutil.rmtree(os.path.join(path, addon_name))
            remove_repo = input(f"do you also want to remove the repo for {addon_name}? y/n")
            if remove_repo.lower() in ["yes", "y"]:
                del addons[addon_name]


if __name__ == '__main__':
    with open("settings.json") as sf:
        settings = json.load(sf)
        sf.close()
    with open("addons.json") as af:
        addons = json.load(af)
        af.close()
    zip_names = []
    while True:
        option = main_menu()
        if option in ["5", "exit"]:
            break
        if option in ["1", "update"]:
            update()
        elif option in ["2", "add"]:
            add_addon()
        elif option in ["3", "settings"]:
            edit_settings()
        elif option in ["4", "remove"]:
            remove()

    with open("settings.json", "w") as sfile:
        json.dump(settings, sfile)
    with open("addons.json", "w") as afile:
        json.dump(addons, afile)

    if zip_names:
        cleanup = input("remove downloaded zip files before exiting? y/n")
        if cleanup.lower() in ["y", "yes"]:
            print("removing....")
            for name in zip_names:
                os.remove(name)
    print("by by")
