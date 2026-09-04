# github-templates

Shared GitHub Actions building blocks for Merkleye repositories.

Every Merkleye repo had grown its own copy of the same CI: the same
Conventional-Commits PR-title check, the same Cloudflare Pages preview
lifecycle (the prune script was byte-for-byte identical in two repos), the
same per-PR container image publish, the same semantic-release scaffolding.
Copies drift. Two repos were already pinned to different `jdx/mise-action`
commits for no reason anyone chose.

This repo holds the parts that are genuinely the same everywhere, as
**reusable workflows** and **composite actions**. It deliberately does not
hold anything repo-specific — no Go test job, no Flutter build, no OpenAPI
contract run. Those belong next to the code they test.

## What's here

### Reusable workflows — `uses:` at the job level

| Workflow | What it does |
| --- | --- |
| [`pr-title.yml`](.github/workflows/pr-title.yml) | Validates a PR title against Conventional Commits. |
| [`cf-pages-preview-cleanup.yml`](.github/workflows/cf-pages-preview-cleanup.yml) | Deletes a PR's Cloudflare Pages preview when the PR closes, and rewrites the preview comment. |
| [`cf-pages-preview-prune.yml`](.github/workflows/cf-pages-preview-prune.yml) | Scheduled safety net: deletes preview deployments older than N days. |
| [`ghcr-pr-preview-image.yml`](.github/workflows/ghcr-pr-preview-image.yml) | Builds and pushes per-PR container images to GHCR under `pr-<n>` tags. |
| [`ghcr-pr-preview-cleanup.yml`](.github/workflows/ghcr-pr-preview-cleanup.yml) | Deletes those preview package versions when the PR closes. |
| [`semantic-release.yml`](.github/workflows/semantic-release.yml) | Assembles the environment semantic-release needs and runs it. |

### Composite actions — `uses:` at the step level

| Action | What it does |
| --- | --- |
| [`setup-mise`](.github/actions/setup-mise) | Installs the toolchain pinned in the calling repo's `mise.toml`. One pin of `jdx/mise-action` for the whole org. |
| [`cf-pages-deploy`](.github/actions/cf-pages-deploy) | Publishes a built directory to Cloudflare Pages, production or per-PR preview, with the sticky preview comment. |
| [`cf-pages-prune`](.github/actions/cf-pages-prune) | Deletes Cloudflare Pages preview deployments by branch alias or age. Never touches production. |

Ready-to-paste caller workflows live in [`examples/`](examples).

## Using them

Reference everything at the `v1` tag:

```yaml
# .github/workflows/pr-title.yml
name: PR Title

on:
  pull_request_target:
    types: [opened, edited, synchronize, reopened]

permissions:
  pull-requests: read

jobs:
  title:
    uses: Merkleye/github-templates/.github/workflows/pr-title.yml@v1
```

That is the whole file. Every input has a default that matches what the org
already does.

### Prerequisite: Actions access

This repository is **private**, so each repo that calls these workflows needs
them shared with it. In this repo: **Settings → Actions → General → Access →
_Accessible from repositories in the Merkleye organization_**. Without it, a
caller fails with `workflow was not found`.

### Extending, not forking

The templates take inputs rather than assumptions. Three levels, in order of
preference:

1. **Override an input.** Runner label, allowed commit types, image list,
   preview retention, registry — all inputs. `examples/pr-title-customised.yml`
   shows the full surface of one workflow.
2. **Keep the repo-specific half local.** The Cloudflare templates deploy and
   clean up; they never build. Your build step, your Lighthouse gate, your
   artifact upload stay in your own workflow, and the template handles the
   part that was identical anyway. `examples/cf-pages-preview-deploy.yml` is
   this shape.
3. **Add an input here.** If two repos need the same new knob, it belongs in
   the template. Open a PR — that is cheaper for everyone than a fourth copy
   of a workflow.

A repo whose need is genuinely singular should just keep its own workflow.
Not everything is a template, and a template with one caller is worse than
the file it replaced.

## Versioning

`v1` is a moving major tag: it always points at the newest backwards-
compatible release of the `1.x` line, the same convention `actions/checkout`
uses. Callers pin to `@v1` and get fixes without doing anything.

- **Backwards-compatible** — a new input with a default, a bumped action pin,
  a clearer summary: merged to `main`, then `v1` is moved forward.
- **Breaking** — an input removed or renamed, a default that changes
  behaviour, a new required secret: gets `v2`, and `v1` stays where it is
  until every caller has moved.

Pin to an exact commit SHA instead of `@v1` if a repo wants to opt out of
automatic updates entirely.

Reusable workflows reference this repo's own composite actions by full path
at `@v1` — self-referential on purpose, so that a caller pinned to `@v1` gets
one coherent set of workflows *and* actions rather than a mix.

## Conventions this repo holds itself to

- **Every third-party action is pinned to a full commit SHA**, with the human
  version in a trailing comment. `scripts/check-action-pins.py` fails CI
  otherwise. A mutable tag here would be a mutable tag in every repo that
  calls these workflows.
- **Least privilege.** Workflows declare `permissions: {}` at the top and each
  job asks for exactly what it needs. Callers do the same.
- **No PR code runs with write scope.** The container preview refuses to
  publish from forks rather than reaching for `pull_request_target`, and the
  PR-title check — which runs nothing from the PR — is the one place
  `pull_request_target` is used.
- **Comments say why, not what.** Anyone can read `uses: docker/login-action`.
  What earns a comment is the reason a step is shaped the way it is.

## Known gaps

- `useblacksmith/*` actions are referenced by major tag, not SHA. Blacksmith
  does not publish SHA-addressable releases that stay valid across runner
  image updates. `scripts/check-action-pins.py` allowlists that prefix; the
  allowlist is the record of the exception.
- The Cloudflare preview templates cover cleanup, prune and deploy but not
  the build, because no two repos build the same way. If a third static site
  appears with the same Astro shape as the others, a `build-astro-site`
  action is the right next addition.
- `semantic-release.yml` handles the environment, not the release config.
  Repos that also publish container images do that through their own
  `.releaserc` exec plugin — a shared release-images script would be a
  reasonable v1.1 once a second repo needs one.
