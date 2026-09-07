#!/usr/bin/env python3
"""Enforce the org's `uses:` conventions across a repo's workflows and actions.

Two rules, both configurable by the action's inputs:

  * Every third-party action is pinned to a full commit SHA. A mutable tag is
    a supply-chain hole in a normal repo and an amplified one in a template
    repo, where it becomes a mutable tag in every consumer.

  * Some actions must not be referenced directly at all, because the org
    wraps them. `jdx/mise-action` is the standing case: wrapping it in
    `setup-mise` is what makes the pin one number for the whole org instead
    of one number per repo that agrees until the first Renovate PR lands
    unevenly. A repo holding its own copy of that pin has opted out of the
    standardisation without saying so.

Deliberately regex over `uses:` rather than a YAML parse: this has to read
composite actions and reusable workflows alike, actionlint already owns
schema validation, and a file too broken to parse is actionlint's failure to
report, not this script's.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")


def parse_banned(raw: str) -> list[tuple[str, str]]:
    """Parse `<prefix> <replacement>` lines into pairs.

    The replacement is what makes the failure actionable — "don't use this"
    without "use that instead" just gets worked around.
    """
    banned = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        prefix, _, replacement = line.partition(" ")
        banned.append((prefix.strip(), replacement.strip()))
    return banned


def parse_list(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def wrapper_paths(banned: list[tuple[str, str]]) -> set[pathlib.Path]:
    """The files that are themselves the sanctioned replacement.

    `setup-mise` exists precisely to reference `jdx/mise-action`, so banning
    that reference org-wide has to exempt the one file allowed to hold it —
    otherwise the rule forbids its own implementation.

    Derived rather than configured: a replacement of the form
    `owner/repo/some/path@ref` names the action at `some/path`, so
    `some/path/action.yml` is the wrapper. In a consuming repo that file does
    not exist and nothing is exempted, which is the behaviour that rule wants
    everywhere except here.
    """
    paths = set()
    for _, replacement in banned:
        if not replacement:
            continue
        ref = replacement.split("@", 1)[0]
        parts = ref.split("/")
        # owner/repo/<path...> — fewer segments is a top-level action, which
        # has no in-repo file to exempt.
        if len(parts) < 3:
            continue
        action_dir = pathlib.Path(*parts[2:])
        paths.add(action_dir / "action.yml")
        paths.add(action_dir / "action.yaml")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default="")
    parser.add_argument("--allow-tags", default="")
    parser.add_argument("--banned", default="")
    parser.add_argument("--require-sha-pins", default="true")
    args = parser.parse_args()

    roots = [pathlib.Path(p) for p in parse_list(args.paths)]
    allow_tags = tuple(parse_list(args.allow_tags))
    banned = parse_banned(args.banned)
    require_pins = args.require_sha_pins.lower() == "true"

    files: list[pathlib.Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(root.rglob("*.yml"))
            files.extend(root.rglob("*.yaml"))
    files = sorted(set(files))

    if not files:
        print(f"No workflow or action files found under: {', '.join(map(str, roots))}")
        return 0

    exempt = wrapper_paths(banned)
    problems: list[str] = []
    unpinned = 0
    checked = 0

    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in USES.finditer(text):
            ref = match.group("ref").strip("\"'")
            line = text[: match.start()].count("\n") + 1

            # A local action path carries no version to pin and cannot be a
            # third party.
            if ref.startswith("./"):
                continue

            checked += 1

            if path not in exempt:
                hit = next((b for b in banned if ref.startswith(b[0])), None)
                if hit:
                    prefix, replacement = hit
                    fix = f" — use {replacement} instead" if replacement else ""
                    problems.append(f"{path}:{line}: `{prefix}` must not be used directly{fix}")
                    continue

            if not require_pins:
                continue
            if any(ref.startswith(p) for p in allow_tags):
                continue

            if "@" not in ref:
                unpinned += 1
                problems.append(f"{path}:{line}: `{ref}` has no version at all")
                continue

            if not SHA.match(ref.rsplit("@", 1)[1]):
                unpinned += 1
                problems.append(
                    f"{path}:{line}: `{ref}` is pinned to a mutable ref, not a commit SHA"
                )

    if problems:
        print(f"{len(problems)} problem(s) found:\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        # Only when something is actually unpinned — printing the pinning
        # recipe under a ban failure sends the reader after the wrong fix.
        if unpinned:
            print(
                "\nPin each third-party action to a full 40-character commit SHA with the"
                "\nversion in a trailing comment, e.g.:"
                "\n  uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
                file=sys.stderr,
            )
        return 1

    print(f"OK — {checked} action reference(s) across {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
