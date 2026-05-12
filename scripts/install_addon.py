from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_SOURCE = REPO_ROOT / "addon"
ADDON_MODULE_NAME = "scad2gn"
DEFAULT_BLENDER_VERSION = "5.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the SCAD2GN Blender add-on into the user add-ons directory."
    )
    parser.add_argument(
        "--blender-version",
        help=f"Blender version directory to install into, for example 4.2. Defaults to the latest detected version or {DEFAULT_BLENDER_VERSION}.",
    )
    parser.add_argument(
        "--addons-dir",
        help="Explicit Blender user add-ons directory. Overrides --blender-version.",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "link", "copy"),
        default="auto",
        help="Install mode. auto tries link first and falls back to copy.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing scad2gn add-on directory at the target path.",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable the add-on by launching Blender in background mode after installation.",
    )
    parser.add_argument(
        "--blender",
        default="blender",
        help="Blender executable used with --enable. Defaults to 'blender' from PATH.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (ADDON_SOURCE / "__init__.py").exists():
        raise SystemExit(f"Add-on source is missing: {ADDON_SOURCE}")

    addons_dir = Path(args.addons_dir).expanduser() if args.addons_dir else default_addons_dir(args.blender_version)
    addons_dir.mkdir(parents=True, exist_ok=True)
    target = addons_dir / ADDON_MODULE_NAME

    install_addon(target, args.mode, force=args.force)
    print(f"Installed {ADDON_MODULE_NAME} to {target}")

    if args.enable:
        enable_addon(args.blender)
        print(f"Enabled {ADDON_MODULE_NAME} in Blender user preferences")
    else:
        print("Enable it in Blender: Edit > Preferences > Add-ons > search SCAD2GN")

    return 0


def default_addons_dir(version: str | None) -> Path:
    blender_root = blender_user_config_root()
    selected_version = version or detect_latest_blender_version(blender_root) or DEFAULT_BLENDER_VERSION
    return blender_root / selected_version / "scripts" / "addons"


def blender_user_config_root() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise SystemExit("APPDATA is not set; pass --addons-dir explicitly.")
        return Path(appdata) / "Blender Foundation" / "Blender"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Blender"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "blender"


def detect_latest_blender_version(blender_root: Path) -> str | None:
    if not blender_root.exists():
        return None

    versions = []
    for child in blender_root.iterdir():
        if child.is_dir():
            try:
                major, minor = child.name.split(".", maxsplit=1)
                versions.append((int(major), int(minor), child.name))
            except ValueError:
                continue

    if not versions:
        return None
    return max(versions)[2]


def install_addon(target: Path, mode: str, *, force: bool) -> None:
    if target.exists() or target.is_symlink():
        handle_existing_target(target, force=force)

    if mode in {"auto", "link"}:
        try:
            create_link(target)
            return
        except OSError as error:
            if mode == "link":
                raise SystemExit(f"Link install failed: {error}") from error
            print(f"Link install failed, falling back to copy: {error}")

    shutil.copytree(ADDON_SOURCE, target)


def handle_existing_target(target: Path, *, force: bool) -> None:
    if points_to_source(target):
        remove_target(target)
        return

    if not force:
        raise SystemExit(f"Target already exists: {target}\nUse --force to replace it.")

    remove_target(target)


def points_to_source(target: Path) -> bool:
    try:
        return target.resolve() == ADDON_SOURCE.resolve()
    except OSError:
        return False


def remove_target(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)


def create_link(target: Path) -> None:
    try:
        target.symlink_to(ADDON_SOURCE, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        create_windows_junction(target)


def create_windows_junction(target: Path) -> None:
    command = ["cmd", "/c", "mklink", "/J", str(target), str(ADDON_SOURCE)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "mklink failed"
        raise OSError(message)


def enable_addon(blender_executable: str) -> None:
    script = (
        "import addon_utils, bpy; "
        f"addon_utils.enable({ADDON_MODULE_NAME!r}, default_set=True, persistent=True); "
        "bpy.ops.wm.save_userpref()"
    )
    result = subprocess.run(
        [blender_executable, "--background", "--python-expr", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            "Failed to enable the add-on with Blender.\n"
            f"Command: {blender_executable} --background --python-expr <script>\n"
            f"{result.stdout}{result.stderr}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
