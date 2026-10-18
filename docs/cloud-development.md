# Cloud development for the Codex project

The local Codex project `潜渊症模组开发` contains two independent Git repositories:

1. BaroDock: `laohei-moddeveloper/barotrauma-mod-assistant`.
2. Rebound Guard: `laohei-moddeveloper/barotrauma-rebound-guard` (the local `ReboundGuard-Project` folder).

Create one Codex Cloud environment and select **both GitHub repositories**. Configure Python 3.12 for BaroDock. Let Codex inspect both repositories and record the setup it successfully tests, then publish the environment. Use a cloud task's intended repository and branch when starting work.

The environment can work with repository source, tests, documentation, and assets that have been committed and pushed. A new local branch or an uncommitted file is not automatically available in cloud tasks. For each repository, push every branch that should be available, including new branches created later; verify with `git ls-remote --heads origin`. The reusable environment may need to be republished if its tools or configuration change, while ordinary source changes belong in Git.

BaroDock's full isolated test command is `python -m unittest discover -s tests -v` on Windows; `.github/workflows/windows-tests.yml` runs it on GitHub Actions. Windows UI, Steam, Barotrauma, local game files, LuaCs, and Windows packaging require a suitable Windows machine. Cloud code review or tests do not establish that these integrations work.

Rebound Guard's public source and instructions are in its own repository. Its private migration bundle, game DLL caches, raw field reports, and other ignored files must stay local. Check that repository's `AGENTS.md` and `.gitignore` before staging files.

Keep durable project guidance in each repository's `AGENTS.md` and task-specific context in the relevant source or docs. Local-only Codex chats, memories, tools, and uncommitted changes are not a substitute for committed project files.
