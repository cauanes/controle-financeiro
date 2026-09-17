# Git and Pull Request Workflow Rule

Whenever submitting changes to GitHub:
1. All changes must be developed, tested, and committed on the `dev` branch.
2. Push `dev` branch to remote: `git push origin dev`.
3. Open a Pull Request from `dev` to `main` using GitHub CLI:
   `gh pr create --base main --head dev --title "<concise title>" --body "<description of changes>"`
4. Automatically merge / accept the PR:
   `gh pr merge --merge --auto` or `gh pr merge --merge`
5. Pull and update both local and remote `main` and `dev` branches:
   `git checkout main && git pull origin main && git checkout dev && git pull origin dev`
6. Always ensure both `main` and `dev` remain synchronized and clean.
