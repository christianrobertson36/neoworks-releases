import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("publisher", pathlib.Path(__file__).with_name("publish.py"))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationTests(unittest.TestCase):
    def test_semver_order_and_bad_versions(self):
        key = publisher.version_key
        self.assertLess(key("9.0.0-rust.2"), key("9.0.0-rust.10"))
        self.assertLess(key("9.0.0-rust.10"), key("9.0.0"))
        self.assertLess(key("9.9.0"), key("9.10.0"))
        for invalid in ["9.0", "09.0.0", "9.0.0-01", "../9.0.0", "9.0.0-.."]:
            with self.assertRaises(ValueError):
                key(invalid)

    def test_package_checksum_and_app_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary)
            archive = folder / "package.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("NeoWorks.Photo.exe", b"test fixture")
            metadata = {"appId": "NeoWorks.Photo", "version": "9.0.0-rust.1",
                        "runtime": "native", "channel": "preview",
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "size": archive.stat().st_size}
            path = folder / "release.json"
            path.write_text(json.dumps(metadata))
            self.assertEqual(publisher.validate(folder)[0]["appId"], "NeoWorks.Photo")
            metadata["sha256"] = "0" * 64
            path.write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):
                publisher.validate(folder)

    def test_installer_incompatible_archives_are_rejected(self):
        for bad in ["../outside.exe", "CON.txt", "images\\logo.png", "data.", "image?.png", "neoworks.photo.EXE", "link"]:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temporary:
                folder = pathlib.Path(temporary)
                archive = folder / "package.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    output.writestr("NeoWorks.Photo.exe", b"fixture")
                    if bad == "link":
                        info = zipfile.ZipInfo("link")
                        info.create_system = 3
                        info.external_attr = 0o120777 << 16
                        output.writestr(info, b"outside")
                    else:
                        output.writestr(bad, b"fixture")
                metadata = {"appId": "NeoWorks.Photo", "version": "9.0.0-rust.1",
                            "runtime": "native", "channel": "preview",
                            "sha256": publisher.digest(archive), "size": archive.stat().st_size}
                (folder / "release.json").write_text(json.dumps(metadata))
                with self.assertRaises(ValueError):
                    publisher.validate(folder)


if __name__ == "__main__":
    unittest.main()
