# Branch Cleanup Procedure

**Repository:** `canstralian/rif-runtime`
**Trigger:** a successful release (a `v*.*.*` tag pushed and the
[Release workflow](../.github/workflows/release.yml) green), or a periodic
stale-branch audit.

RIF Runtime follows a lightweight trunk-based workflow: `main` is the only
long-lived branch, and every other branch is temporary — created for one
change, merged via pull request, then deleted. There is no `develop` branch,
and `release/*` / `hotfix/*` are reserved patterns that are protected if they
ever come into use.

## Objective

Remove completed development branches after a release while preserving
repository history, release traceability, and active work. Merged commits
live on in `main`; deleting the source branch loses nothing.

## Preconditions

Verify all of the following before beginning:

- [ ] Release tag created and pushed (`git tag --sort=-creatordate`)
- [ ] The Release workflow for that tag passed (it runs ruff, mypy, pytest,
      and `rif replay` before publishing)
- [ ] `pyproject.toml` and `src/rif_runtime/__init__.py` versions were bumped
      together for the release
- [ ] All required pull requests merged
- [ ] No open work depends on branches scheduled for deletion
- [ ] No pending release fixes are expected
- [ ] A rollback point exists: the release tag plus the build artifacts the
      Release workflow attached to the GitHub Release (`dist/*`)

## Procedure

### 1. Synchronize the repository

```bash
git switch main
git fetch --all --prune --tags
git pull --ff-only origin main
```

`git switch` is the modern replacement for `git checkout` when changing
branches, `--ff-only` prevents unintended merge commits, and `--tags` ensures
release tags are synchronized before you verify them.

### 2. Verify the release

```bash
git tag --sort=-creatordate     # confirm the expected tag is newest
git show v0.2.1                 # confirm the tag points at the expected commit
```

A tag alone is not the complete release artifact. Also confirm on GitHub
that the Release exists for the tag, the generated release notes were
published, and the built assets (`dist/*`) were uploaded — these are your
rollback point once source branches are gone.

Treat release tags as immutable — never move or delete one.

### 3. Run the cleanup script (recommended)

The scripted path is preferred over manual deletion:

```bash
./scripts/cleanup_branches.sh              # dry run: lists deletable branches
./scripts/cleanup_branches.sh --delete     # actually deletes them on the remote
```

The script only considers remote branches whose history is fully merged into
`origin/main`, and always skips `main`, `release/*`, and `hotfix/*`. A branch
with unmerged commits is never touched, so nothing can be lost. Review the dry
run output before passing `--delete`.

### 4. Manual cleanup (alternative)

List merged branches — check the remote as well as local, since a branch that
is only merged locally is not safe to delete on the remote:

```bash
git branch --merged main                     # local
git branch -r --merged origin/main           # remote
```

Never delete `main`, `release/*`, `hotfix/*`, or any branch with ongoing work.

Delete merged branches:

```bash
git branch -d feature/example                # local; -d refuses unmerged work
git push origin --delete feature/example     # remote
```

To clear many merged local branches at once after a large release:

```bash
git branch --merged main |
  grep -Ev '^\*|^\s*(main|release/|hotfix/)' |
  while read -r branch; do git branch -d "$branch"; done
```

Only use `git branch -D` after independently verifying the branch was merged
(e.g. its pull request shows as merged on GitHub).

### 5. Prune remote references

```bash
git fetch --prune
```

### 6. Review repository state

```bash
git branch      # local
git branch -r   # remote
```

Expected remaining long-lived branches: `main` (plus `release/*` / `hotfix/*`
if any are active).

### 7. Verify branch protection

Ensure protection remains enabled for `main` (and `release/*` / `hotfix/*` if
used): required pull requests, required status checks, signed commits if
enforced, no force pushes, no branch deletion.

**Required status check:** `gate`, from `.github/workflows/merge-gate.yml`.
That job aggregates lock-sync, `verify` (3.12 and 3.13), clean-clone and
dependency-security into a single verdict, and is designed to be the only
required check — see the comments in that workflow.

> **Migration note.** `ci.yml`, `quality.yml` and `lint.yml` were removed; their
> ruff/mypy/pytest work was already duplicated by `merge-gate.yml`'s `verify`
> matrix. If branch protection still lists checks from those workflows as
> required, they will never report again and `main` cannot be merged. Remove
> them and require `gate` instead. Optionally also require `coverage` and
> `build and smoke` from the new `Coverage` and `Image` workflows.

### 8. Update release documentation

Review and update as needed: release notes (auto-generated by the Release
workflow), `README.md` if features changed, `docs/ARCHITECTURE.md`,
`docs/API.md`, and `docs/ROADMAP.md`.

## Final verification

| Item                                            | Complete |
| ----------------------------------------------- | -------- |
| Release tag pushed                              | ☐        |
| Release workflow green (ruff, mypy, pytest, replay) | ☐    |
| GitHub Release published with notes and assets  | ☐        |
| Smoke test passed (`scripts/smoke.sh`)          | ☐        |
| Rollback point confirmed (tag + release assets) | ☐        |
| Local branches removed                          | ☐        |
| Remote branches removed                         | ☐        |
| Remote references pruned                        | ☐        |
| Documentation updated                           | ☐        |
| Branch protection verified                      | ☐        |

## Branch model

Long-lived:

```
main
release/*   (reserved, currently unused)
hotfix/*    (reserved, currently unused)
```

Temporary (delete immediately after merge):

```
feature/* feat/*  fix/* bugfix/*  docs/*  ci/*  chore/*  refactor/*  test/*
experiment/*  prototype/*  spike/*
claude/*  codex/*   (agent-created working branches)
```

If the branching strategy ever evolves toward Git Flow, `develop` becomes an
additional long-lived branch; the rest of this procedure applies unchanged
(add `develop` to the protected list and to the cleanup script's
`PROTECTED` pattern).

## GitHub automation

Enable automatic deletion of merged branches so most cleanup never needs to
happen manually:

> Settings → General → Pull Requests → **Automatically delete head branches**

This deletes a pull request's head branch on merge while preserving the
commits in `main` (GitHub also offers a one-click restore on the PR page).
The procedure above then only needs to catch branches that were merged before
the setting was enabled, or that never went through a pull request.

Further automation worth enabling as the project grows:

- Branch protection rules with required status checks (already recommended
  above)
- A merge queue, once multiple contributors land changes concurrently
- Scheduled pruning of stale branches, e.g. a periodic run of
  `scripts/cleanup_branches.sh` in dry-run mode to surface candidates

## Best practices

- Never delete branches containing unmerged commits.
- Create and push the release tag before cleanup, and treat tags as immutable.
- Protect long-lived branches with branch protection rules.
- Prune remote references after deleting branches.
- Perform branch cleanup immediately after each release.
- Periodically audit stale branches (for example, branches inactive for more
  than 90 days) — the dry-run mode of `scripts/cleanup_branches.sh` is a
  quick way to see what is already merged and safe to remove.
