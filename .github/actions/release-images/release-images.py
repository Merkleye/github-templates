#!/usr/bin/env python3
"""Build, push and tag every container image a release ships.

Run by semantic-release's @semantic-release/exec prepareCmd, through the path
the release-images action puts in the environment:

    "prepareCmd": "python3 \"$MERKLEYE_RELEASE_IMAGES\" ${nextRelease.version}"

Invoked through the interpreter rather than by path, on purpose. A script run
by path depends on its committed mode bit, and that bit is easy to lose:
`git update-index --chmod=+x` writes the index but not the working tree, so the
next commit touching the file records whatever mode is on disk and silently
reverts it. `python3 <file>` cannot fail that way.

Inside prepareCmd rather than as a later workflow step, also on purpose: a
build that fails here aborts the release before semantic-release tags the
commit or creates the GitHub Release. Moving it after would leave a published
release pointing at an image that was never pushed.

Only build, push and tag. The SBOM is the template's job (`sbom: true` in
semantic-release.yml), which scans the pushed image and attaches the result to
the Release that semantic-release just cut.

Environment, all set by the release-images action:
  MERKLEYE_IMAGES       required. JSON array of {image, context, file}, the
                        same shape container-ci.yml and the preview workflow
                        take, so a repo declares its image set once.
  MERKLEYE_REGISTRY     registry and namespace. Defaults to
                        ghcr.io/<owner of GITHUB_REPOSITORY>.
  CONTAINER_PLATFORMS   defaults to linux/amd64,linux/arm64.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from typing import NoReturn

DEFAULT_PLATFORMS = "linux/amd64,linux/arm64"
REQUIRED_KEYS = ("image", "context", "file")


def fail(message: str) -> NoReturn:
    print(f"release-images: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_images() -> list[dict]:
    raw = os.environ.get("MERKLEYE_IMAGES", "").strip()
    if not raw:
        fail(
            "MERKLEYE_IMAGES is empty. It is set by the release-images action, "
            "from semantic-release.yml's `images` input — a container release "
            "needs that input."
        )
    try:
        images = json.loads(raw)
    except json.JSONDecodeError as err:
        fail(f"MERKLEYE_IMAGES is not valid JSON: {err}")
    if not isinstance(images, list) or not images:
        fail("MERKLEYE_IMAGES must be a non-empty JSON array.")
    for entry in images:
        if not isinstance(entry, dict):
            fail(f"image entry {entry!r} is not an object.")
        missing = [key for key in REQUIRED_KEYS if not entry.get(key)]
        if missing:
            fail(f"image entry {entry!r} is missing: {', '.join(missing)}")
    return images


def registry() -> str:
    explicit = os.environ.get("MERKLEYE_REGISTRY", "").strip()
    if explicit:
        return explicit.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        fail("MERKLEYE_REGISTRY is unset and GITHUB_REPOSITORY is not owner/repo.")
    # GHCR namespaces are lowercase; the org name in GITHUB_REPOSITORY is not.
    return f"ghcr.io/{repo.split('/')[0].lower()}"


def run(argv: list[str], *, dry_run: bool = False, capture: bool = False) -> str:
    printable = " ".join(shlex.quote(arg) for arg in argv)
    print(f"+ {printable}", flush=True)
    if dry_run:
        return ""
    # A list, never a shell string: image names and paths come from repo config
    # and never become shell words.
    result = subprocess.run(
        argv, check=False, text=True, stdout=subprocess.PIPE if capture else None
    )
    if result.returncode != 0:
        fail(f"command failed ({result.returncode}): {printable}")
    return result.stdout or ""


def build_argv(
    ref: str,
    version: str,
    major: str,
    platforms: str,
    entry: dict,
    oci: dict[str, str],
) -> list[str]:
    """Assemble the buildx invocation, including the three published tags.

    v1.2.3 pins an exact build, v1 tracks the newest 1.x, latest tracks the
    newest release. semantic-release only moves forward on a release branch, so
    overwriting the two moving tags is always correct.
    """
    argv = [
        "docker", "buildx", "build",
        "--push",
        "--platform", platforms,
        "--tag", f"{ref}:v{version}",
        "--tag", f"{ref}:v{major}",
        "--tag", f"{ref}:latest",
    ]
    for key, value in oci.items():
        argv += ["--build-arg", f"{key}={value}"]
    argv += ["--file", entry["file"], entry["context"]]
    return argv


def oci_build_args(version: str, dry_run: bool) -> dict[str, str]:
    revision = (
        "0" * 40
        if dry_run
        else run(["git", "rev-parse", "HEAD"], capture=True).strip()
    )
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    return {
        "OCI_VERSION": version,
        "OCI_REVISION": revision,
        "OCI_CREATED": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "OCI_REF_NAME": f"v{version}",
        "OCI_SOURCE": f"{server}/{repo}",
    }


def main() -> int:
    argv = sys.argv[1:]

    # `--check` is what the release-images action runs at job setup: it reports
    # a malformed `images` input while the job is still assembling, instead of
    # halfway through a release that has already analyzed commits.
    if "--check" in argv:
        images = load_images()
        names = ", ".join(entry["image"] for entry in images)
        print(f"release-images: {len(images)} image(s) to publish: {names}")
        return 0

    # The SBOM step reads the image list back through here rather than parsing
    # MERKLEYE_IMAGES itself, so what gets scanned cannot diverge from what got
    # built.
    if "--list-images" in argv:
        for entry in load_images():
            print(entry["image"])
        return 0

    dry_run = "--dry-run" in argv
    positional = [
        arg for arg in argv
        if arg not in ("--dry-run", "--check", "--list-images")
    ]
    if len(positional) != 1:
        fail("usage: release-images.py <version> [--dry-run] | --check | --list-images")

    version = positional[0].lstrip("v")
    major = version.split(".")[0]
    if not major.isdigit():
        fail(f"cannot read a major version from {positional[0]!r}")

    images = load_images()
    reg = registry()
    platforms = (
        os.environ.get("CONTAINER_PLATFORMS", "").strip() or DEFAULT_PLATFORMS
    )
    oci = oci_build_args(version, dry_run)

    for entry in images:
        ref = f"{reg}/{entry['image']}"
        print(f"::group::Build + push {entry['image']}")
        run(build_argv(ref, version, major, platforms, entry, oci), dry_run=dry_run)
        print("::endgroup::")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
