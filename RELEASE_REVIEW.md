# Proposed public source release review

Decision: APPROVE for sanitized source-content review; publication remains pending
owner license choice and final authorization. No commit, staging, upload, push,
repository visibility change, external service, or actual model call was performed.
This directory has no Git history. Audit-only baseline hashes remain outside it.

## Included files

The exact inventory and security decisions are in RELEASE_MANIFEST.json.
All listed files passed source-content review and residual-literal/path/credential
signature checks. Synthetic credential-like strings in mock tests are intentional,
not real credentials. No private runtime inputs or proprietary media were copied.
LICENSE is absent and pending owner decision.

## Changes relative to live source

- GUI: generic identity and labels; configurable model/reference path. Class
  control flow is unchanged after excluding text literals.
- Manuscript and narrative legacy retrievers: optional configured entity lists.
- Canon legacy helper: generic retrieval/identity rules and configured answers,
  empty by default; private deterministic facts and passage patterns removed.
- Legacy guard: optional configured unsupported-pattern rules and generic prompt.
- Legacy index reader/query/helpers: consistent generic chunk filename.
- Discovery/read tool: environment/project-relative workspace, containment checks,
  generic help, and portable reparse-attribute access.
- Manual voice demo: imports and runtime work moved behind main().
- Added validated configuration module, empty example JSON, generic Modelfile,
  current README, direct dependency lists, and release-specific synthetic tests.
- Core scene-answer and evidence-anchor modules are byte-identical to live source.
  Workspace research helper, voice helper, and two existing offline test files
  are also byte-identical.
- No application behavior or source file in the live project was changed.

The deliberately sanitized areas differ from the private application. Generic
configuration does not reproduce private story rules. Legacy helper names were
generalized, and personal drive routing was replaced by workspace routing.
No portrait assets are required; the GUI text fallback remains.

## Verification

51 offline synthetic tests passed; 0 failures, errors, skips, or forbidden calls.
Coverage includes retrieval and v3.1.6 validation/verifier regression tests plus
13 release-specific tests for config, generic legacy helpers, workspace boundaries,
manual-demo import safety, source compilation, and local import symbol contracts.
Network connections, subprocesses, and model-package imports were blocked during
the preparation test run. Only synthetic temporary documents were created.
Python files compiled in memory; no GUI, audio, model, dependency installation,
or external endpoint was executed. Third-party imports were checked statically
against dependency declarations; actual GUI/voice import/runtime checks remain open.

## Remaining release tasks

- Owner chooses LICENSE; do not infer permission to distribute original IP.
- Select/test dependency versions and optionally lock environments. The dependency
  lists are direct, unpinned declarations, not a verified reproducible lock.
- Review third-party library, voice, and model license obligations.
- GUI, platform audio, and model integrations require separate authorized testing.
- Runtime logs, histories, index contents/source-path metadata, and fallback excerpts
  can contain private material; keep all generated files out of the release.
- Existing verifier timeout/token limits and heuristic entailment limitations remain.
- Public/private GitHub visibility was not queried.

## Proposed Git release procedure (NOT executed)

1. Review this exact directory and manifest. Resolve LICENSE and dependency policy.
   Add a chosen LICENSE only after owner approval, then scan it, add one exact
   .gitignore exception, and regenerate manifest hashes before proceeding.
2. Use a fresh empty repository directory outside the live project. Copy only
   manifest-listed files with their relative paths; never copy .git or the audit
   parent directory. Verify each supplied SHA-256 before any Git operation.
3. After explicit authorization for Git writes, initialize the fresh repository:

       git init -b main

4. Read RELEASE_MANIFEST.json and add only its exact paths (PowerShell):

       $releaseFiles = @((Get-Content -LiteralPath RELEASE_MANIFEST.json -Raw | ConvertFrom-Json).files | ForEach-Object { $_.path })
       git add -- $releaseFiles
       git diff --cached --name-only
       git diff --cached --check
       git diff --cached
       git status --short

   Compare the staged list exactly with the approved manifest. Do not force-add
   files or use broad recursive additions. Re-run source security checks and the
   documented offline synthetic tests. Inspect the staged diff locally, without
   sending private content to another service.
5. Only after separate commit authorization, create the source-review commit.
   Confirm its tree contains only approved source files and no imported history.
6. Only after separate publication authorization, verify the intended remote,
   owner, and visibility; then add that remote and push the reviewed branch.
   Never push the existing live repository or its history as part of this procedure.

These instructions propose future actions; no Git-write command above was run.
