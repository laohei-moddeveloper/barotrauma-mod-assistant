# BaroDock repository guidance

- This Git repository is one part of the Codex project `潜渊症模组开发`. The local project folder also contains `ReboundGuard-Project`, a separate Git repository with its own remote and instructions. Do not copy its files into this repository.
- Use Python 3.12. Application code uses the standard library; `requirements-build.txt` is for Windows packaging. See `README.md` and `docs/validation.md` for the development and validation commands.
- Run `python -m unittest discover -s tests -v` on Windows for the full isolated suite. The existing GitHub Actions workflow runs these checks on `windows-2022`. Report any cloud-hosted checks separately from Windows results.
- The Tkinter desktop app, Steamworks DLL, Barotrauma installation, game configuration, and Windows EXE build need a suitable Windows machine. Cloud tasks can edit and review the repository without claiming these local integrations were exercised.
- Keep personal settings, logs, installed game files, third-party mod contents, credentials, generated build output, and local research out of Git. Review staged paths before committing.
- Every branch intended for continued work in Codex Cloud must exist on `origin`. After creating or updating a local branch, commit the intended files, push that branch, and verify its remote ref. Do not merge one branch into another merely to make it visible to cloud tasks.
- A Codex Cloud task should work from the branch named for that task. Commit and push useful results so later tasks and other worktrees can see them.
- Steam Workshop publication and release installation are separate from source synchronization; follow the release instructions when explicitly requested.
