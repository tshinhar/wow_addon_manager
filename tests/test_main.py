import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

import main


def _make_zip_bytes(files_dict):
    """Create an in-memory zip archive from a dict of {arcname: content_str}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files_dict.items():
            zf.writestr(path, content)
    buf.seek(0)
    return buf.read()


class TestConfigAndProfiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = self.temp_dir.name
        main.settings = main.normalize_settings({})
        main.addons = main.normalize_addons({})
        main.zip_names.clear()

    def tearDown(self):
        main.zip_names.clear()
        self.temp_dir.cleanup()

    def test_normalize_legacy_settings(self):
        raw = {"addons_path": "C:\\Games\\WoW\\Interface\\AddOns"}
        norm = main.normalize_settings(raw)
        self.assertEqual(norm["addons_path"], "C:\\Games\\WoW\\Interface\\AddOns")
        self.assertEqual(norm["wow_forever_addons_path"], "")
        self.assertEqual(norm["active_game"], main.GAME_WOW)
        self.assertEqual(norm["version"], main.DEFAULT_VERSION)

    def test_normalize_settings_invalid_game_defaults_to_wow(self):
        norm = main.normalize_settings({"active_game": "invalid_game"})
        self.assertEqual(norm["active_game"], main.GAME_WOW)

    def test_normalize_legacy_addons_migrates_to_wow(self):
        legacy = {
            "BigWigs": "https://github.com/BigWigsMods/BigWigs",
            "Details": "https://github.com/Tercioo/Details-Damage-Meter",
        }
        norm = main.normalize_addons(legacy)
        self.assertEqual(norm[main.GAME_WOW], legacy)
        self.assertEqual(norm[main.GAME_WOW_FOREVER], {})

    def test_normalize_dual_game_addons_preserved(self):
        dual = {
            "wow": {"BigWigs": "https://github.com/BigWigsMods/BigWigs"},
            "wow_forever": {"Questie": "https://github.com/Questie/Questie"},
        }
        norm = main.normalize_addons(dual)
        self.assertEqual(norm[main.GAME_WOW], dual["wow"])
        self.assertEqual(norm[main.GAME_WOW_FOREVER], dual["wow_forever"])

    def test_save_and_load_settings_and_addons(self):
        settings_path = os.path.join(self.tmp, "settings.json")
        addons_path = os.path.join(self.tmp, "addons.json")

        main.settings = main.normalize_settings({
            "addons_path": "/wow/addons",
            "wow_forever_addons_path": "/forever/addons",
            "active_game": main.GAME_WOW_FOREVER,
            "version": "2.0.0",
        })
        main.addons = main.normalize_addons({
            "wow": {"AddonA": "https://github.com/u/a"},
            "wow_forever": {"AddonB": "1234567"},
        })

        main.save_settings(settings_path)
        main.save_addons(addons_path)

        main.settings = {}
        main.addons = {}

        loaded_s = main.load_settings(settings_path)
        loaded_a = main.load_addons(addons_path)

        self.assertEqual(loaded_s["addons_path"], "/wow/addons")
        self.assertEqual(loaded_s["wow_forever_addons_path"], "/forever/addons")
        self.assertEqual(loaded_s["active_game"], main.GAME_WOW_FOREVER)
        self.assertEqual(loaded_s["version"], "2.0.0")
        self.assertEqual(loaded_a["wow"], {"AddonA": "https://github.com/u/a"})
        self.assertEqual(loaded_a["wow_forever"], {"AddonB": "1234567"})

    def test_game_switching_and_path_helpers(self):
        main.set_game_addons_path("/path/wow", main.GAME_WOW)
        main.set_game_addons_path("/path/forever", main.GAME_WOW_FOREVER)

        main.set_active_game(main.GAME_WOW)
        self.assertEqual(main.get_active_game(), main.GAME_WOW)
        self.assertEqual(main.get_game_addons_path(), "/path/wow")

        main.set_active_game(main.GAME_WOW_FOREVER)
        self.assertEqual(main.get_active_game(), main.GAME_WOW_FOREVER)
        self.assertEqual(main.get_game_addons_path(), "/path/forever")

        with self.assertRaises(ValueError):
            main.set_active_game("unknown_game")

    def test_parse_github_repo(self):
        self.assertEqual(
            main.parse_github_repo("https://github.com/BigWigsMods/BigWigs"),
            ("BigWigsMods", "BigWigs"),
        )
        self.assertEqual(
            main.parse_github_repo("https://github.com/BigWigsMods/BigWigs.git/"),
            ("BigWigsMods", "BigWigs"),
        )
        self.assertEqual(
            main.parse_github_repo("owner/repo"),
            ("owner", "repo"),
        )
        with self.assertRaises(ValueError):
            main.parse_github_repo("invalid_url")


class TestAddonOperations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = self.temp_dir.name
        self.wow_dir = os.path.join(self.tmp, "wow_addons")
        self.forever_dir = os.path.join(self.tmp, "forever_addons")
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)

        main.settings = main.normalize_settings({
            "addons_path": self.wow_dir,
            "wow_forever_addons_path": self.forever_dir,
            "active_game": main.GAME_WOW,
            "version": "1.0.0",
        })
        main.addons = main.normalize_addons({
            "wow": {
                "BigWigs": "https://github.com/BigWigsMods/BigWigs",
                "SourceOnlyAddon": "https://github.com/owner/source_addon",
            },
            "wow_forever": {
                "ForeverCFAddon": "1234567",
            },
        })
        main.zip_names.clear()

    def tearDown(self):
        os.chdir(self.old_cwd)
        main.zip_names.clear()
        self.temp_dir.cleanup()

    def test_update_separates_wow_and_wow_forever_installs(self):
        wow_zip = _make_zip_bytes({"BigWigs/BigWigs.toc": "## Title: BigWigs"})
        source_zip = _make_zip_bytes({"source_addon-main/source.toc": "## Title: Source"})
        forever_zip = _make_zip_bytes({"ForeverCF/ForeverCF.toc": "## Title: ForeverCF"})

        def fake_get(url, stream=False, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "api.github.com/repos/BigWigsMods/BigWigs/releases/latest" in url:
                resp.json.return_value = {
                    "assets": [
                        {
                            "name": "BigWigs.zip",
                            "browser_download_url": "https://example.com/BigWigs.zip",
                        }
                    ]
                }
            elif url == "https://example.com/BigWigs.zip":
                resp.iter_content = lambda chunk_size=8192: [wow_zip]
            elif "api.github.com/repos/owner/source_addon/releases/latest" in url:
                resp.json.return_value = {
                    "assets": [],
                    "zipball_url": "https://example.com/source_addon_zipball.zip",
                }
            elif url == "https://example.com/source_addon_zipball.zip":
                resp.iter_content = lambda chunk_size=8192: [source_zip]
            elif "curseforge.com/api/v1/mods/1234567/files" in url:
                resp.json.return_value = {
                    "data": [{"id": 7654321, "fileName": "ForeverCF.zip"}]
                }
            elif url == "https://mediafilez.forgecdn.net/files/7654/321/ForeverCF.zip":
                resp.iter_content = lambda chunk_size=8192: [forever_zip]
            else:
                raise AssertionError(f"Unexpected URL: {url}")
            return resp

        with patch("main.requests.get", side_effect=fake_get):
            # Update WoW addons (with source zip fallback accepted)
            rc_wow = main.update(
                game=main.GAME_WOW,
                log_func=lambda _: None,
                prompt_source_func=lambda addon: True,
            )
            self.assertEqual(rc_wow, 0)
            self.assertTrue(os.path.isfile(os.path.join(self.wow_dir, "BigWigs", "BigWigs.toc")))
            self.assertTrue(
                os.path.isfile(os.path.join(self.wow_dir, "source_addon-main", "source.toc"))
            )
            self.assertFalse(os.path.exists(self.forever_dir))

            # Update WoW Forever addons
            rc_forever = main.update(
                game=main.GAME_WOW_FOREVER,
                log_func=lambda _: None,
            )
            self.assertEqual(rc_forever, 0)
            self.assertTrue(
                os.path.isfile(os.path.join(self.forever_dir, "ForeverCF", "ForeverCF.toc"))
            )
            self.assertFalse(os.path.exists(os.path.join(self.wow_dir, "ForeverCF")))

            # Clean up downloaded zips
            removed = main.cleanup_downloaded_zips(log_func=lambda _: None)
            self.assertEqual(len(removed), 3)
            self.assertEqual(main.zip_names, [])

    def test_update_missing_path_returns_error(self):
        main.set_game_addons_path("", main.GAME_WOW_FOREVER)
        rc = main.update(game=main.GAME_WOW_FOREVER, log_func=lambda _: None)
        self.assertEqual(rc, 1)

    def test_remove_all_addons_for_active_game(self):
        os.makedirs(os.path.join(self.wow_dir, "BigWigs"), exist_ok=True)
        os.makedirs(os.path.join(self.forever_dir, "ForeverCFAddon"), exist_ok=True)

        # Remove all from WoW Forever; ensure WoW folder is untouched
        with patch("builtins.input", side_effect=["all", "y", "y"]):
            rc = main.remove(game=main.GAME_WOW_FOREVER)
        self.assertEqual(rc, 0)
        self.assertEqual(main.get_installed_addon_dirs(main.GAME_WOW_FOREVER), [])
        self.assertNotIn("ForeverCFAddon", main.get_game_addons(main.GAME_WOW_FOREVER))
        self.assertEqual(main.get_installed_addon_dirs(main.GAME_WOW), ["BigWigs"])


class TestSelfUpdate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = self.temp_dir.name
        main.settings = main.normalize_settings({
            "addons_path": "/custom/wow/path",
            "wow_forever_addons_path": "/custom/forever/path",
            "active_game": main.GAME_WOW_FOREVER,
            "version": "1.0.0",
        })
        main.addons = main.normalize_addons({
            "wow": {"MyWowAddon": "https://github.com/u/wow"},
            "wow_forever": {"MyForeverAddon": "https://github.com/u/forever"},
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_self_update_preserves_user_configs_and_updates_version(self):
        app_dir = os.path.join(self.tmp, "app")
        os.makedirs(app_dir, exist_ok=True)
        main.save_settings(os.path.join(app_dir, "settings.json"))
        main.save_addons(os.path.join(app_dir, "addons.json"))

        # Simulate a release zip containing a new executable AND default settings/addons JSONs
        release_zip = _make_zip_bytes({
            "wow_addon_manager/wow_addon_manager.exe": "UPDATED_BINARY",
            "wow_addon_manager/new_file.txt": "NEW_ASSET",
            "wow_addon_manager/settings.json": '{"addons_path": "DEFAULT_OVERWRITE"}',
            "wow_addon_manager/addons.json": '{"wow": {}, "wow_forever": {}}',
        })

        def fake_get(url, stream=False, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "api.github.com/repos/tshinhar/wow_addon_manager/releases/latest" in url:
                resp.json.return_value = {
                    "tag_name": "2403010000",
                    "assets": [
                        {
                            "name": "wow_addon_manager.zip",
                            "browser_download_url": "https://example.com/wow_addon_manager.zip",
                        }
                    ],
                }
            elif url == "https://example.com/wow_addon_manager.zip":
                resp.iter_content = lambda chunk_size=8192: [release_zip]
            else:
                raise AssertionError(f"Unexpected URL: {url}")
            return resp

        with patch("main.requests.get", side_effect=fake_get):
            rc = main.self_update(
                log_func=lambda _: None,
                target_dir=app_dir,
            )

        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(app_dir, "wow_addon_manager.exe")))
        self.assertTrue(os.path.isfile(os.path.join(app_dir, "new_file.txt")))

        # Verify user's settings.json and addons.json were preserved, and version was updated
        with open(os.path.join(app_dir, "settings.json"), "r", encoding="utf-8") as sf:
            saved_settings = json.load(sf)
        self.assertEqual(saved_settings["addons_path"], "/custom/wow/path")
        self.assertEqual(saved_settings["wow_forever_addons_path"], "/custom/forever/path")
        self.assertEqual(saved_settings["active_game"], main.GAME_WOW_FOREVER)
        self.assertEqual(saved_settings["version"], "2403010000")

        with open(os.path.join(app_dir, "addons.json"), "r", encoding="utf-8") as af:
            saved_addons = json.load(af)
        self.assertIn("MyWowAddon", saved_addons["wow"])
        self.assertIn("MyForeverAddon", saved_addons["wow_forever"])

    def test_self_update_skips_when_already_up_to_date(self):
        main.settings["version"] = "2403010000"

        def fake_get(url, stream=False, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "tag_name": "2403010000",
                "assets": [
                    {
                        "name": "wow_addon_manager.zip",
                        "browser_download_url": "https://example.com/wow_addon_manager.zip",
                    }
                ],
            }
            return resp

        with patch("main.requests.get", side_effect=fake_get) as mock_get:
            rc = main.self_update(log_func=lambda _: None)
            self.assertEqual(rc, 0)
            # Only the release metadata call should have been made, no download call
            self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
