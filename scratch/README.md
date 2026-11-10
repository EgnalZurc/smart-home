# scratch/ — Local Git Worktrees

`scratch/` is reserved for **local git worktrees** used to develop branches in parallel without touching the main working tree. This directory is gitignored; its contents must not be committed.

## Standard

- **Location and naming:** create worktrees only under `scratch/` with a short, descriptive name: `scratch/wt-<slug>` (one branch/task per worktree).
- **When to use:** only when parallel work or isolation is needed for a concrete branch/PR. For a single sequential task, prefer working on a branch in the main checkout.
- **Limit:** at most **1 active worktree per task**. Do not create worktrees by default.
- **No pollution:** never `git add`, stage, or commit anything under `scratch/` in the main checkout.
- **Lifecycle / TTL:** remove worktrees promptly after the related PR is merged or closed.
  - `git worktree remove <path>` (use `--force` only after verifying there is no unique uncommitted work)
  - `git worktree prune`
  - delete the local branch if no longer needed (`git branch -D <branch>`)
- **Hygiene:** periodically verify with `git worktree list` (only the main worktree should remain when idle) and keep `git status` clean.

## For AI/agent sessions

- Do not create git worktrees or use `scratch/` unless parallelism is explicitly needed for a concrete task/PR.
- Before removing a worktree/branch, verify the work is merged (or intentionally discarded) and that no unique local changes will be lost.
- Leave the repository clean at the end of the session (no leftover worktrees, no staged `scratch/*` paths).
