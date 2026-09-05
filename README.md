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

Reference everything at `main`:

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
    uses: Merkleye/github-templates/.github/workflows/pr-title.yml@main
```

That is the whole file. Every input has a default that matches what the org
already does.

### Adopting the PR-title check: use `pull_request`

`pull_request_target` reads the workflow file from the **base** branch, so a
workflow that exists only on a PR branch never runs — no check, no failure,
nothing to notice. The PR that adopts the check gets no signal from it at
all, and it only starts working once that PR merges.

So adopt with `pull_request`, which runs from the PR's own branch and makes
the adopting PR its own proof. Switch to `pull_request_target` afterwards if
the repo wants the rules pinned to the base branch — nothing in this check
executes PR code, so either is safe.

### Why this repository is public

It holds workflow YAML, one bash script and this README — no secrets, no
credentials, nothing proprietary.

It is public because it has to be. A **public** repository cannot consume
actions or reusable workflows from a private one, and no org setting closes
that gap: the "accessible from repositories in the organization" toggle
shares a private repo with the org's *private* repos only. Merkleye has
public repos in the set (`merkleye-website`, `certspotter`, `dnstwist`,
`certstream-server`), so a private templates repo would have left them
either duplicating what everything else shares, or reaching for a read
token and a checkout to work around it.

Nothing here should ever need to be secret. If a template ever needs a
value that does, the value belongs in the calling repo's secrets and reaches
the template through a `secrets:` input — never inlined here.

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

Callers track `main`. There is no version ref to move and nothing to bump on
release — merging here is the release, and every consuming repo picks the
change up on its next run.

That is the right trade for this org: one team, eight repos, and templates
whose blast radius is visible in the PR that changes them. A `v1` ref would
add a step to every change and a second thing to get wrong, to buy staged
rollout that nobody here is asking for.

The cost is real and worth stating plainly: **a bad merge to `main` reaches
every repo at once.** What stands between a change and that is this repo's
own CI — actionlint over the workflows *and* the examples, shellcheck over
the scripts, and the pin check — plus the fact that every consumer's next PR
exercises the templates for real. Protect `main` and require those checks
before more than a couple of people are pushing here.

A repo that wants to opt out of automatic updates pins to an exact commit
SHA instead:

```yaml
uses: Merkleye/github-templates/.github/workflows/pr-title.yml@a54a9da...
```

If staged rollout is ever genuinely needed — a breaking input change with
consumers that cannot all move at once — the answer is a `v2` path or a
release tag introduced at that point, not a version ref maintained
speculatively from the start.

Reusable workflows reference this repo's own composite actions by full path
at `@main`, self-referentially, so a workflow and the actions it calls are
always read from the same commit rather than a mix.

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
  reasonable addition once a second repo needs one.
