"""Publish approved binary ZIPs without copying private product source."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import zipfile

REPO = "christianrobertson36/neoworks-releases"
APPS = {
    "NeoWorks.Photo": "NeoWorks.Photo.exe",
    "NeoWorks.Writer": "NeoWorks.Writer.exe",
    "NeoWorks.Sheet": "NeoWorks.Sheet.exe",
    "NeoWorks.Pdf": "NeoWorks.Pdf.exe",
    "NeoWorks.Design": "NeoWorks.Design.exe",
    "NeoWorks.Database": "NeoWorks.Database.exe",
    "NeoWorks.Calendar": "NeoWorks.Calendar.exe",
    "NeoWorks.Launcher": "NeoWorks-Launcher.exe",
}


def version_key(value):
    number = r"(?:0|[1-9][0-9]*)"
    match = re.fullmatch(fr"({number})\.({number})\.({number})(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", value)
    if not match:
        raise ValueError("Invalid semantic version")
    pre = match.group(4)
    identifiers = []
    for item in pre.split(".") if pre else []:
        if item.isdigit():
            if len(item) > 1 and item.startswith("0"):
                raise ValueError("Invalid prerelease number")
            identifiers.append((0, int(item)))
        else:
            identifiers.append((1, item))
    return (*map(int, match.group(1, 2, 3)), pre is None, identifiers)


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validate(folder):
    metadata = json.loads((folder / "release.json").read_text())
    app = metadata["appId"]
    version = metadata["version"]
    channel = metadata["channel"]
    version_key(version)
    if app not in APPS:
        raise ValueError("Invalid app or version")
    if channel not in ("stable", "preview") or metadata["runtime"] not in ("native", "dotnet"):
        raise ValueError("Invalid channel or runtime")
    if channel == "stable" and "-" in version:
        raise ValueError("Prerelease versions belong in the preview catalogue")
    package = folder / "package.zip"
    if package.stat().st_size != metadata["size"] or digest(package) != metadata["sha256"]:
        raise ValueError("Package checksum/size mismatch")
    if not 0 < metadata["size"] <= 2 * 1024**3:
        raise ValueError("Invalid package size")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) > 20000 or sum(info.file_size for info in archive.infolist()) > 4 * 1024**3:
            raise ValueError("Expanded archive exceeds installer limits")
        seen = set()
        for info in archive.infolist():
            name = info.filename
            if not name or name.startswith("/") or any(char in name for char in '\\:\x00<>"|?*') or any(ord(char) < 32 for char in name):
                raise ValueError("Unsafe archive path")
            if name.lower() in seen:
                raise ValueError("Duplicate Windows archive path")
            seen.add(name.lower())
            for part in name.rstrip("/").split("/"):
                stem = part.split(".")[0].upper()
                if not part or part in (".", "..") or part.endswith((".", " ")) or stem in ("CON", "PRN", "AUX", "NUL") or re.fullmatch(r"(COM|LPT)[0-9]", stem):
                    raise ValueError("Unsafe Windows archive path")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive links are unsupported")
            if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("Unsupported archive encoding")
        if archive.testzip() is not None:
            raise ValueError("Corrupt archive entry")
        if APPS[app] not in names:
            raise ValueError("Missing app executable")
        if metadata["runtime"] == "dotnet":
            stem = APPS[app][:-4]
            if stem + ".dll" not in names or stem + ".runtimeconfig.json" not in names:
                raise ValueError("Incomplete managed package")
    return metadata, package


def publish(folder):
    metadata, package = validate(folder)
    app, version = metadata["appId"], metadata["version"]
    tag = f"{app}-v{version}-{metadata['channel']}"
    filename = f"{app}-{version}-Windows-x64.zip"
    release = subprocess.run(["gh", "release", "view", tag, "--repo", REPO], capture_output=True)
    with tempfile.TemporaryDirectory() as temp:
        asset = pathlib.Path(temp) / filename
        shutil.copyfile(package, asset)
        if release.returncode:
            args = ["release", "create", tag, str(asset), "--repo", REPO,
                    "--title", f"{app} {version}", "--notes",
                    metadata.get("releaseNotes", "NeoWorks development release."),
                    "--latest=false"]
            if metadata["channel"] == "preview":
                args.append("--prerelease")
            gh(*args)
        else:
            # Retry a partially finished release without replacing published assets.
            details = json.loads(gh("api", f"repos/{REPO}/releases/tags/{tag}"))
            if not any(item["name"] == filename for item in details["assets"]):
                gh("release", "upload", tag, str(asset), "--repo", REPO)
        downloaded = pathlib.Path(temp) / "verified"
        downloaded.mkdir()
        gh("release", "download", tag, "--repo", REPO, "--pattern", filename, "--dir", str(downloaded))
        verified = downloaded / filename
        if verified.stat().st_size != metadata["size"] or digest(verified) != metadata["sha256"]:
            raise ValueError("Published release bytes differ; catalogue was not updated")
    url = f"https://github.com/{REPO}/releases/download/{urllib.parse.quote(tag, safe='')}/{urllib.parse.quote(filename, safe='')}"
    if app != "NeoWorks.Launcher":
        path = pathlib.Path("catalogue") / (metadata["channel"] + ".json")
        catalogue = json.loads(path.read_text())
        current = next((item for item in catalogue["apps"] if item["appId"] == app), None)
        if current and version_key(current["version"]) > version_key(version):
            return url
        entry = {key: metadata[key] for key in ("appId", "version", "runtime", "sha256", "size")}
        entry["url"] = url
        entry["releaseNotes"] = metadata.get("releaseNotes", "")
        catalogue["apps"] = [item for item in catalogue["apps"] if item["appId"] != app] + [entry]
        catalogue["apps"].sort(key=lambda item: item["appId"])
        path.write_text(json.dumps(catalogue, indent=2) + "\n")
    else:
        path = pathlib.Path("catalogue/launcher-" + metadata["channel"] + ".json")
        if path.exists() and version_key(json.loads(path.read_text())["latestVersion"]) > version_key(version):
            return url
        path.write_text(json.dumps({"latestVersion": version, "downloadUrl": url,
                                   "sha256": metadata["sha256"]}, indent=2) + "\n")
    return url


if __name__ == "__main__":
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("Publisher must run in the public downloads repository")
    for metadata_path in sorted(pathlib.Path("incoming").glob("*/release.json")):
        print(publish(metadata_path.parent))
