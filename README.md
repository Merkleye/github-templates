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
| [`container-ci.yml`](.github/workflows/container-ci.yml) | Builds every image a repo ships and pushes nothing — the container-integrity gate. |
| [`workflow-lint.yml`](.github/workflows/workflow-lint.yml) | actionlint, plus the org's `uses:` rules: SHA-pinned actions and no direct `jdx/mise-action`. |
| [`semantic-release.yml`](.github/workflows/semantic-release.yml) | Assembles the environment semantic-release needs and runs it, container builder and registry login included. |

### Composite actions — `uses:` at the step level

| Action | What it does |
| --- | --- |
| [`setup-mise`](.github/actions/setup-mise) | Installs the toolchain pinned in the calling repo's `mise.toml`, optionally in a named mise environment. One pin of `jdx/mise-action` for the whole org. |
| [`cf-pages-deploy`](.github/actions/cf-pages-deploy) | Publishes a built directory to Cloudflare Pages, production or per-PR preview, with the sticky preview comment. |
| [`cf-pages-prune`](.github/actions/cf-pages-prune) | Deletes Cloudflare Pages preview deployments by branch alias or age. Never touches production. |
| [`resolve-builder`](.github/actions/resolve-builder) | Turns `auto` into `docker` or `blacksmith` from the runner label. One definition of `auto` for the three workflows that build images. |
| [`lint-workflows`](.github/actions/lint-workflows) | The step-level half of `workflow-lint.yml`, for a repo that already has a lint job to hang it on. |

Ready-to-paste caller workflows live in [`examples/`](examples), including
[`mise-tasks.yml`](examples/mise-tasks.yml) for the step-level `setup-mise`
pattern.

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

### The mise convention

Every Merkleye repo pins its toolchain in `mise.toml`, so every workflow in
every repo starts with the same installer step. That step is
[`setup-mise`](.github/actions/setup-mise) — one pinned `jdx/mise-action`
for the whole org, bumped by one Renovate PR here instead of drifting per
repo and per workflow. Use it in place of the raw action:

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
- uses: Merkleye/github-templates/.github/actions/setup-mise@main
- run: mise run test
```

The second half of the convention is that CI runs **`mise run <task>`**, not
the command the task wraps. A repo that already has a `Makefile` keeps it —
`mise.toml` wraps each target (`run = "make test"`) rather than restating it,
so `make test` and `mise run test` are the same thing by construction and
there is one definition of what the gate is. `merkleye` is that shape;
`mcp-server` defines its tasks in `mise.toml` directly. Both are fine. What
is not fine is a workflow inlining `gofmt -l .` next to a `fmt-check` target
that has since grown an exclusion.

There is no reusable workflow for this, deliberately. The repeatable part is
the installer, and `setup-mise` is it; the task names belong to the repo, and
a template that only forwarded a list of them would add a hop without
removing a copy. `examples/mise-tasks.yml` is the pattern to paste.

A tool that only one kind of run needs still belongs in mise, not in a
workflow input. `mise.release.toml` is loaded on top of `mise.toml` when
`MISE_ENV=release`, which is what `semantic-release.yml` sets by default:

```toml
# mise.release.toml -- tools only a release needs
[tools]
syft = "1"
```

`setup-mise` takes the same thing as `env:` for a step-level caller. The point
is that the version lives with the rest of the toolchain, a contributor can
run the release steps locally by exporting the same variable, and a PR run
does not install a tool it never invokes. An `install-<tool>: true` input
would have bought none of that and would have needed a new input per tool.

Two exceptions worth knowing before converting a lint step:

- **`golangci-lint` stays on `golangci/golangci-lint-action`.** The release
  pinned in `mise.toml` is itself built with an older Go than these modules
  target and refuses to load a newer language version; the action fetches a
  build that matches the runner. `mise run lint` stays for local use.
- **A step that needs setup mise does not provide** — a `pip install` of a
  library, a browser, a service container — keeps that setup in the workflow.
  The task is still `mise run <task>`.

### Runners and builders

Every workflow here takes a `runs-on` input defaulting to `ubuntu-latest`.
One label, whichever kind of runner it names:

```yaml
runs-on: ubuntu-latest                    # GitHub-hosted
runs-on: blacksmith-2vcpu-ubuntu-2404     # Blacksmith
runs-on: self-hosted                      # your own pool
```

It is a single label, not a JSON array. A self-hosted pool that needs
distinguishing should carry its own label rather than being addressed by
AND-ing `[self-hosted, linux, x64]` — that is the shape every runner here
already has, and it keeps one input type across every template.

The three workflows that build containers take a second, separate input:
`builder`, which chooses between `docker/*` and `useblacksmith/*` actions.
It defaults to `auto`, which reads the runner label — anything containing
`blacksmith` gets the Blacksmith builder, everything else gets Buildx — so
the common case is one input, not two.

They are separate inputs because the choice is genuinely separate: running
the docker builder on a Blacksmith runner is a legitimate thing to want, and
`auto` would otherwise make it unsayable. Set `builder` explicitly and it
wins.

`auto` logs which builder it picked. A wrong guess is otherwise invisible
until a build behaves oddly for reasons nobody can see in the YAML.

### Enforcing the conventions

A convention nobody checks is a convention that decays. `setup-mise` existed
for a while before anyone noticed that `design` still pinned
`jdx/mise-action` at five call sites and `merkleye-website` at one — they
agreed with the shared pin at the time, so nothing looked wrong, and they
would have disagreed the first time a Renovate PR landed in one repo and not
the other.

[`workflow-lint.yml`](.github/workflows/workflow-lint.yml) is the check.
One job, no inputs in the common case:

```yaml
jobs:
  lint:
    permissions:
      contents: read
    uses: Merkleye/github-templates/.github/workflows/workflow-lint.yml@main
```

It runs actionlint over the repo's workflows, then walks both
`.github/workflows` and `.github/actions` — composite actions are where the
last unpinned references tend to hide — and fails on two things:

- a third-party action not pinned to a full commit SHA
- a `uses:` that names an action the org wraps, naming the wrapper to use
  instead

Both rules are inputs, so a repo with a real exception declares it in its own
caller where a reviewer sees it, rather than being unable to adopt the check
at all. `examples/workflow-lint.yml` shows both overrides. Note they replace
the defaults rather than adding to them.

The wrapper itself is exempt automatically: `setup-mise` exists precisely to
reference `jdx/mise-action`, and a rule that forbids its own implementation
is a rule nobody can satisfy. That is derived from the replacement path, not
configured.

### Why this repository is public

It holds workflow YAML, two small scripts and this README — no secrets, no
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
  version in a trailing comment. A mutable tag here would be a mutable tag in
  every repo that calls these workflows.
- **`jdx/mise-action` is referenced only by `setup-mise`.** One pin for the
  org, moved by one Renovate PR. A repo holding its own copy has opted out of
  that without saying so — see "Enforcing the conventions" below.
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
  image updates. `lint-workflows`' `allow-tags` default carries that prefix;
  the allowlist is the record of the exception.
- The Cloudflare preview templates cover cleanup, prune and deploy but not
  the build, because no two repos build the same way. If a third static site
  appears with the same Astro shape as the others, a `build-astro-site`
  action is the right next addition.
- `semantic-release.yml` handles the environment, not the release config.
  It now assembles the container half of that environment too — builder and
  registry login — but what gets built, tagged and attached still lives in
  each repo's `.releaserc` exec plugin and its `scripts/release-image.sh`.
  `container-platforms` reaches those scripts as `$CONTAINER_PLATFORMS`, so
  the platform list at least is the caller's to set rather than a constant
  buried in each script.
  Those scripts are near-identical in `merkleye`, `certspotter` and
  `dnstwist`; a shared one is the obvious next extraction, and it is a script
  rather than a workflow, so it wants an `sh` file in this repo and a
  `curl`-free way to reach it. That is the part not yet designed.
- `container-ci.yml` builds and throws the image away. It does not scan it,
  test it, or check that it starts. `merkleye`'s perf suite runs the dnstwist
  sidecar for real, but that is a repo-specific job, not a template. If a
  second repo wants "does the container come up and answer /health", that is
  a worthwhile input to add here rather than a third copy.
