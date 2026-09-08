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

An SBOM per image per platform comes with it, and is not optional. A published
image without one is the gap, and a release that publishes images is the only
moment the information exists; making it a per-repo switch would have meant
every repo deciding the same thing again, and one of them getting it wrong.
Per platform because a multi-arch manifest list has different packages on each
architecture, so the list digest is not a meaningful scan target -- syft
against it resolves to whichever platform the runner happens to be.

syft is not installed here. It is pinned in the repo's mise.release.toml like
the rest of the toolchain and comes off PATH as a shim; this fails with the
lines to add if the toolchain does not pin it. Which version runs stays a
property of the repo's toolchain, and only the plumbing is shared.

The SBOMs land in MERKLEYE_SBOM_DIR inside the workspace so the repo's
@semantic-release/github `assets` glob uploads them to the Release. prepare
runs before publish, so they exist by the time that plugin looks.

Environment, all set by the release-images action except the last:
  MERKLEYE_IMAGES       required. JSON array of {image, context, file}, the
                        same shape container-ci.yml and the preview workflow
                        take, so a repo declares its image set once.
  MERKLEYE_REGISTRY     registry and namespace. Defaults to
                        ghcr.io/<owner of GITHUB_REPOSITORY>.
  CONTAINER_PLATFORMS   defaults to linux/amd64,linux/arm64.
  MERKLEYE_SBOM_DIR     where the SBOMs are written. Defaults to sbom/, which
                        is what the repos' assets glob names.
"""

from __future__ import annotations

import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import NoReturn

DEFAULT_PLATFORMS = "linux/amd64,linux/arm64"
DEFAULT_SBOM_DIR = "sbom"
SBOM_FORMAT = "spdx-json"
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


def require_syft() -> None:
    if shutil.which("syft"):
        return
    fail(
        "syft is not on PATH. A release that publishes images generates an "
        "SBOM for each one, and the version is the repo's to pin. Add it to "
        'mise.release.toml:\n\n[tools]\nsyft = "1"\n'
    )


def sbom_image(ref: str, version: str, sbom_dir: pathlib.Path, image: str,
               dry_run: bool) -> None:
    """One SBOM per linux platform in the image's manifest list."""
    raw = run(
        ["docker", "buildx", "imagetools", "inspect", f"{ref}:v{version}", "--raw"],
        dry_run=dry_run,
        capture=True,
    )
    if dry_run:
        # Nothing was pushed, so there is no manifest to read back. Show the
        # shape of what would be scanned rather than inventing a digest.
        print(f"+ syft registry:{ref}@<digest per platform> "
              f"-o {SBOM_FORMAT}={sbom_dir}/{image}-<arch>.spdx.json")
        return

    manifests = json.loads(raw).get("manifests", [])
    if not manifests:
        fail(f"{ref}:v{version} has no manifest list to scan.")
    scanned = 0
    for manifest in manifests:
        platform = manifest.get("platform", {})
        # Attestation and unknown entries carry platform.os == "unknown".
        if platform.get("os") != "linux":
            continue
        arch = platform.get("architecture", "unknown")
        out = sbom_dir / f"{image}-{arch}.{SBOM_FORMAT.replace('-', '.')}"
        run(["syft", f"registry:{ref}@{manifest['digest']}",
             "-o", f"{SBOM_FORMAT}={out}"], dry_run=False)
        scanned += 1
    if not scanned:
        fail(f"{ref}:v{version} has no linux platform to scan.")


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
    sbom_dir = pathlib.Path(
        os.environ.get("MERKLEYE_SBOM_DIR", "").strip() or DEFAULT_SBOM_DIR
    )

    # Before the first build, not after it: a missing syft should not be
    # discovered once images are already pushed and the release is half done.
    if not dry_run:
        require_syft()
        sbom_dir.mkdir(parents=True, exist_ok=True)

    for entry in images:
        image = entry["image"]
        ref = f"{reg}/{image}"

        print(f"::group::Build + push {image}")
        run(build_argv(ref, version, major, platforms, entry, oci), dry_run=dry_run)
        print("::endgroup::")

        print(f"::group::SBOM {image}")
        sbom_image(ref, version, sbom_dir, image, dry_run)
        print("::endgroup::")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
