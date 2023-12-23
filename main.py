"""
this is the main section of the wow addon manager
created by tshinhar
"""
import json
import requests
import os
import zipfile


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
    name = input("what setting do you want to change?")
    if name not in settings:
        print("this setting dose not exist, check your spelling!")
        return 1
    value = input("insert new value for the setting")
    settings[name] = value
    return 0


def add_addon():
    """add an addon"""
    print(f"current addons:\n{addons}")
    new_name = input("give a name to the new addon:")
    url = input("insert the repo url of the addon")
    confirm = input(f"add {new_name} with URL {url}? y/n")
    if confirm.lower() in ["y", "yes"]:
        addons[new_name] = url
        return 0


def update():
    """update all currently listed addons to latest version"""
    for addon in addons:
        owner, repo = addons[addon].lstrip("https://github.com/").split("/")
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        response.raise_for_status()

        release_data = response.json()

        print(f"getting downlaod URL for {repo}")
        download_url = ""
        zip_name = ""
        for asset in release_data["assets"]:
            if asset["name"].endswith(".zip"):
                download_url = asset["browser_download_url"]
                zip_name = asset["name"]
                break
        if not download_url:
            print(f"could not get download URL, make sure the github repo given for {addon} as zip"
                  f"files in it's release")
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
        print(f"successfully installed {repo}")


def remove():
    """removes an addon"""
    print(f"current addons:\n{addons}")
    name = input("which addon you wish to remove?")
    confirm = input(f"are you sure you want to remove {name}? y/n")
    if confirm.lower() in ["y", "yes"]:
        del addons[name]


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

    cleanup = input("remove downloaded zip files before exiting? y/n")
    if cleanup.lower() in ["y", "yes"]:
        print("removing....")
        for name in zip_names:
            os.remove(name)
    print("by by")


