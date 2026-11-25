# Git Branching & Modification Workflow

## Core Rules
1. **Never Make Direct Changes to `demo` or `main`**:
   - All code edits, refactors, and feature additions must take place on a dedicated branch created for that specific scope.

2. **Always Branch from Latest `demo`**:
   - Before creating a new branch or starting work, pull the latest changes from `origin/demo` (`git checkout demo && git pull origin demo`).
   - Create a feature or fix branch from `demo` (e.g., `feature/<name>` or `fix/<name>`).

3. **Confine Edits to the Dedicated Branch**:
   - All intermediate commits and file edits must remain on the newly created branch until explicitly instructed to merge or open a pull request.

4. **Approval Gate Before Merging or Pushing**:
   - Do not commit or push any changes until the user has explicitly reviewed and approved the implementation and test verification.
