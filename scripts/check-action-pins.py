#!/usr/bin/env python3
"""Assert every third-party action in this repo is pinned to a full commit SHA.

A template repo is a supply-chain amplifier: a mutable tag here is a mutable
tag in every repo that calls these workflows. So the rule is stricter than in
a normal repo -- a `uses:` either names a 40-character commit SHA, or it is
one of the two documented exceptions below and says why.

Exceptions:
  * Merkleye/github-templates/...@<ref>  -- this repo referring to itself.
    Pinning it to a SHA would mean rewriting every internal reference on
    every release; the tag is what makes `v1` mean one coherent set.
  * useblacksmith/*                       -- Blacksmith publishes major-version
    tags only and does not keep SHA-addressable releases usable across runner
    image updates. Tracked in the README's "Known gaps".
"""

from __future__ import annotations

import pathlib
import re
import sys

USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")

SELF_PREFIX = "Merkleye/github-templates/"
TAG_ALLOWED_PREFIXES = ("useblacksmith/",)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCH = [ROOT / ".github", ROOT / "examples"]


def main() -> int:
    problems: list[str] = []
    checked = 0

    files = sorted(p for d in SEARCH for p in d.rglob("*.yml"))
    files += sorted(p for d in SEARCH for p in d.rglob("*.yaml"))

    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in USES.finditer(text):
            ref = match.group("ref").strip("\"'")
            line = text[: match.start()].count("\n") + 1
            rel = path.relative_to(ROOT)

            # A local action path carries no version to pin.
            if ref.startswith("./"):
                continue

            checked += 1

            if ref.startswith(SELF_PREFIX):
                continue
            if any(ref.startswith(p) for p in TAG_ALLOWED_PREFIXES):
                continue

            if "@" not in ref:
                problems.append(f"{rel}:{line}: `{ref}` has no version at all")
                continue

            version = ref.rsplit("@", 1)[1]
            if not SHA.match(version):
                problems.append(
                    f"{rel}:{line}: `{ref}` is pinned to a mutable ref, not a commit SHA"
                )

    if problems:
        print("Unpinned actions found:\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nPin each to a full 40-character commit SHA with the version in a"
            "\ntrailing comment, e.g.:"
            "\n  uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            file=sys.stderr,
        )
        return 1

    print(f"OK -- {checked} third-party action reference(s), all pinned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
