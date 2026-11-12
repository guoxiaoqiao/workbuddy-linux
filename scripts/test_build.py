import json
import hashlib
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest

from build import (OFFICIAL_DEPENDS, PACKAGING_REVISION, control_text, electron_version, extract_asar,
                   output_stem,
                   pack_unpacked_asar, patch_bundled_runtime_default, patch_desktop, patch_linux,
                   patch_postrm, patch_postinst,
                   repository_owner, validate_runtime_version, write_md5sums)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, files, data=b""):
        header = json.dumps({"files": files}).encode()
        body = struct.pack("<II", len(header) + 4, len(header)) + header
        archive = self.root / "app.asar"
        archive.write_bytes(struct.pack("<II", 4, len(body)) + body + data)
        return archive

    def test_framework_version_is_read_from_source(self):
        # A future source version must not inherit the packaging host's runtime.
        plist = self.root / "Frameworks/Electron Framework.framework/Versions/A/Resources/Info.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(plistlib.dumps({"CFBundleVersion": "42.3.7"}))
        self.assertEqual(electron_version(self.root), "42.3.7")

    def test_missing_framework_fails(self):
        with self.assertRaises(ValueError):
            electron_version(self.root)

    def test_packed_files_sidecars_and_executable_permissions(self):
        archive = self.archive({
            "main.js": {"offset": "0", "size": 5, "executable": True},
            "native.node": {"size": 3, "unpacked": True},
        }, b"hello")
        sidecar = self.root / "app.asar.unpacked"
        sidecar.mkdir()
        (sidecar / "native.node").write_bytes(b"ELF")
        output = self.root / "out"
        self.assertEqual(extract_asar(archive, output), [])
        self.assertEqual((output / "main.js").read_bytes(), b"hello")
        self.assertEqual((output / "native.node").read_bytes(), b"ELF")
        self.assertTrue((output / "main.js").stat().st_mode & 0o111)

    def test_sidecar_files_missing_from_index_are_mirrored(self):
        archive = self.archive({"main.js": {"offset": "0", "size": 5}} , b"hello")
        sidecar = self.root / "app.asar.unpacked"
        (sidecar / "main/preload").mkdir(parents=True)
        (sidecar / "main/preload/fork-preload.cjs").write_bytes(b"preload")
        output = self.root / "out"
        report = {}
        self.assertEqual(extract_asar(archive, output, report), [])
        self.assertEqual((output / "main/preload/fork-preload.cjs").read_bytes(), b"preload")
        self.assertEqual(report["sidecarOnlyFiles"], ["main/preload/fork-preload.cjs"])

    def test_absent_foreign_sidecar_is_reported_without_placeholder(self):
        archive = self.archive({"win32-x64": {"files": {"addon.node": {"unpacked": True, "size": 3}}}})
        output = self.root / "out"
        self.assertEqual(extract_asar(archive, output), ["win32-x64/addon.node"])
        self.assertFalse((output / "win32-x64/addon.node").exists())

    def test_missing_application_sidecar_fails(self):
        archive = self.archive({"main.js": {"unpacked": True, "size": 3}})
        with self.assertRaises(FileNotFoundError):
            extract_asar(archive, self.root / "out")

    def test_archive_cannot_escape_destination(self):
        archive = self.archive({"..": {"files": {"escaped": {"offset": "0", "size": 1}}}}, b"x")
        with self.assertRaises(ValueError):
            extract_asar(archive, self.root / "out")
        self.assertFalse((self.root / "escaped").exists())

    def test_truncated_packed_file_fails(self):
        archive = self.archive({"main.js": {"offset": "0", "size": 10}}, b"x")
        with self.assertRaises(ValueError):
            extract_asar(archive, self.root / "out")

    def test_changed_im_guard_stops_build(self):
        main = self.root / "main"
        main.mkdir()
        (main / "daemon-bootstrap.js").write_text("function changedUpstream(){}")
        with self.assertRaises(ValueError):
            patch_linux(self.root)

    def test_im_patch_preserves_the_upstream_fallback_for_both_versions(self):
        main = self.root / "main"
        main.mkdir()
        target = main / "daemon-bootstrap.js"
        for fallback in ("createHeadlessImChannelsBackend", "createUnavailableImChannelsBackend"):
            with self.subTest(fallback=fallback):
                target.write_text("function createDesktopImChannelsBackend(e){"
                                  f"if(config()?.isOversea===!0)return {fallback}();"
                                  "return nativeBackend(e)}")
                patch_linux(self.root)
                self.assertEqual(target.read_text(), "function createDesktopImChannelsBackend(e){"
                                 f"if(process.platform===`linux`||config()?.isOversea===!0)return {fallback}();"
                                 "return nativeBackend(e)}")

    def test_vendor_runtime_requires_matching_electron_base(self):
        validate_runtime_version("37.10.3", "37.10.3-24")
        with self.assertRaises(ValueError):
            validate_runtime_version("38.0.0", "37.10.3-24")

    def test_unpacked_asar_roundtrip(self):
        app = self.root / "app.asar.unpacked"
        (app / "main").mkdir(parents=True)
        (app / "main/index.js").write_text("module.exports = 42")
        binary = app / "tool"
        binary.write_bytes(b"ELF")
        binary.chmod(0o755)
        archive = self.root / "app.asar"
        pack_unpacked_asar(app, archive)
        output = self.root / "out"
        self.assertEqual(extract_asar(archive, output), [])
        self.assertEqual((output / "main/index.js").read_text(), "module.exports = 42")
        self.assertTrue((output / "tool").stat().st_mode & 0o111)

    OFFICIAL_POSTRM = """#!/bin/bash

if type update-alternatives >/dev/null 2>&1; then
    update-alternatives --remove 'workbuddy' '/opt/WorkBuddy/workbuddy' || true
    update-alternatives --remove '@genieworkbuddy-desktop' '/opt/WorkBuddy/@genieworkbuddy-desktop' || true
fi

rm -f '/usr/bin/workbuddy' '/usr/bin/@genieworkbuddy-desktop' || true
"""

    OFFICIAL_POSTINST = """#!/bin/bash

set +e

if type gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

if type update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

exit 0
"""

    OFFICIAL_DESKTOP = """[Desktop Entry]
Name=WorkBuddy
Exec=/opt/WorkBuddy/workbuddy %U
Terminal=false
Type=Application
Icon=workbuddy
StartupWMClass=workbuddy
Comment=WorkBuddy Desktop - AI Agent Desktop Application
MimeType=x-scheme-handler/workbuddy;
Categories=Development;
"""

    def test_postrm_removal_is_guarded_by_dpkg_action(self):
        patched = patch_postrm(self.OFFICIAL_POSTRM)
        # The unconditional rm that deletes the new package's launcher during
        # upgrades must only run for remove/purge now.
        self.assertNotIn("\nrm -f '/usr/bin/workbuddy'", patched)
        self.assertIn("remove|purge)", patched)
        self.assertIn("rm -f '/usr/bin/workbuddy' '/usr/bin/@genieworkbuddy-desktop' || true", patched)
        self.assertIn("update-alternatives --remove 'workbuddy'", patched)

    def test_changed_postrm_stops_the_build(self):
        with self.assertRaises(ValueError):
            patch_postrm(self.OFFICIAL_POSTRM.replace("rm -f", "rm  -f"))

    def test_postinst_keeps_cache_refresh_and_adds_launcher_self_heal(self):
        patched = patch_postinst(self.OFFICIAL_POSTINST)
        self.assertIn("gtk-update-icon-cache -f -t /usr/share/icons/hicolor", patched)
        self.assertIn("update-desktop-database /usr/share/applications", patched)
        self.assertIn("exec /opt/WorkBuddy/launch-workbuddy", patched)
        self.assertLess(patched.index("if [ ! -e /usr/bin/workbuddy ]"), patched.rindex("exit 0"))

    def test_changed_postinst_stops_the_build(self):
        without_refresh = self.OFFICIAL_POSTINST.replace("update-desktop-database", "refresh-desktop-db")
        with self.assertRaises(ValueError):
            patch_postinst(without_refresh)
        without_exit = self.OFFICIAL_POSTINST.replace("\nexit 0\n", "\n")
        with self.assertRaises(ValueError):
            patch_postinst(without_exit)

    def test_desktop_adopts_official_entry_with_package_launcher(self):
        patched = patch_desktop(self.OFFICIAL_DESKTOP)
        self.assertIn("Exec=/usr/bin/workbuddy %U", patched)
        self.assertNotIn("/opt/WorkBuddy/workbuddy", patched)
        self.assertIn("Comment[zh_CN]=腾讯云代码助手", patched)
        self.assertIn("Categories=Development;", patched)

    def test_changed_desktop_stops_the_build(self):
        with self.assertRaises(ValueError):
            patch_desktop(self.OFFICIAL_DESKTOP.replace("Exec=/opt/WorkBuddy/workbuddy %U", "Exec=changed"))

    def test_bundled_runtime_defaults_to_disabled(self):
        target = self.root / "app/main/main-bootstrap.js"
        target.parent.mkdir(parents=True)
        target.write_text("const X=1;DEFAULT_BUNDLED_RUNTIME_CONFIG={enabled:!0,"
                          "tools:{node:!0,python:!0,gitBash:!0,brokeredShell:!0}};")
        note = patch_bundled_runtime_default(self.root / "app")
        self.assertIn("DEFAULT_BUNDLED_RUNTIME_CONFIG={enabled:!1,", target.read_text())
        self.assertNotIn("DEFAULT_BUNDLED_RUNTIME_CONFIG={enabled:!0,", target.read_text())
        self.assertEqual(note, "Bundled runtime defaults to disabled (no runtime packaged)")

    def test_changed_bundled_runtime_default_stops_the_build(self):
        target = self.root / "app/main/main-bootstrap.js"
        target.parent.mkdir(parents=True)
        target.write_text("DEFAULT_BUNDLED_RUNTIME_CONFIG={enabled:true};")
        with self.assertRaises(ValueError):
            patch_bundled_runtime_default(self.root / "app")

    def test_md5sums_covers_payload_and_skips_debian_and_links(self):
        package = self.root / "pkg"
        (package / "DEBIAN").mkdir(parents=True)
        payload = package / "opt/WorkBuddy/data.bin"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b"payload")
        link = package / "opt/WorkBuddy/link"
        link.symlink_to("data.bin")
        (package / "DEBIAN/control").write_text("Package: workbuddy\n")
        write_md5sums(package)
        lines = (package / "DEBIAN/md5sums").read_text().splitlines()
        self.assertEqual(lines, [f"{hashlib.md5(b'payload').hexdigest()}  opt/WorkBuddy/data.bin"])

    def test_output_stem_marks_unofficial_repack_with_the_deb_base(self):
        stem = output_stem("5.9.3.42398134-d4692421", "5.6.2.40046327-c7b525f3", "amd64")
        self.assertEqual(
            stem,
            "workbuddy_5.9.3.42398134-d4692421"
            f"_base5.6.2.40046327-c7b525f3_unofficial_repack{PACKAGING_REVISION}_amd64")
        # Keep the donor official deb version visible and avoid the redundant
        # "deb" token the official filenames carry next to the extension.
        self.assertIn("_base5.6.2.40046327-c7b525f3_", stem)
        self.assertIn("_unofficial_", stem)
        self.assertIn(f"_repack{PACKAGING_REVISION}_", stem)
        self.assertNotIn("deb", stem)

    def test_control_aligns_with_the_official_package(self):
        text = control_text("amd64", "5.9.3-3", 1000)
        fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
        self.assertEqual(fields["Section"], "default")
        self.assertEqual(fields["Homepage"], "https://www.workbuddy.cn")
        self.assertEqual(fields["Maintainer"], repository_owner())
        self.assertNotIn("Vendor", fields)
        depends = fields["Depends"].split(", ")
        self.assertTrue(set(OFFICIAL_DEPENDS) <= set(depends))
        self.assertIn("nodejs", depends)
        self.assertIn("imagemagick", fields["Recommends"].split(", "))
        self.assertIn("WorkBuddy Desktop - AI Agent Desktop Application", text)


if __name__ == "__main__":
    unittest.main()
