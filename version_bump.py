import re
import argparse
from pathlib import Path


def read_version(file_path):
    """Reads the current version from the __version__.py file."""
    with open(file_path, "r") as f:
        content = f.read()
        match = re.search(r'__version__\s*=\s*["\']([\d.]+)["\']', content)
        if not match:
            raise ValueError("Version string not found in the file.")
        return match.group(1)


def write_version(file_path, new_version):
    """Writes the new version to the __version__.py file."""
    with open(file_path, "r") as f:
        content = f.read()

    new_content = re.sub(
        r'(__version__\s*=\s*["\'])([\d.]+)(["\'])',
        r'\g<1>' + new_version + r'\g<3>',
        content
    )
    with open(file_path, "w") as f:
        f.write(new_content)


def bump_version(version, part):
    """Increments the specified part of the version (major, minor, patch)."""
    major, minor, patch = map(int, version.split("."))
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError("Invalid part to bump. Choose 'major', 'minor', or 'patch'.")
    return f"{major}.{minor}.{patch}"


def main():
    parser = argparse.ArgumentParser(description="Version bump script for __version__.py")
    parser.add_argument(
        "part",
        help="The part of the version to bump (major, minor, patch)",
        choices=["major", "minor", "patch"]
    )
    args = parser.parse_args()
    version_file = "__version__.py"

    try:
        current_version = read_version(version_file)
        print(f"Current version: {current_version}")

        new_version = bump_version(current_version, args.part)
        print(f"Bumping {args.part} version to: {new_version}")

        write_version(version_file, new_version)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
