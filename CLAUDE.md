@AGENTS.md

# Claude Code harness

AGENTS.md holds the quality gates. This file adds only the wiring that is
specific to Claude Code. `.claude/settings.json` holds that wiring. It mirrors
`.cursor/hooks.json`.

| Event | Matcher | Command | Effect |
| --- | --- | --- | --- |
| `PreToolUse` | `Write\|Edit` | `make complexity-pre` | Denies a new or worse breach before the write reaches disk |
| `PostToolUse` | `Write\|Edit` | `scripts/hooks/post-edit.sh` | Runs `make lint-fix FILE=…` on the edited file |
| `PostToolUse` | `Write\|Edit` | `scripts/hooks/post-plan.sh` | Reports unresolved paths and `make` targets in a plan artifact |
| `PostToolUse` | `Bash` | `scripts/hooks/post-bash.sh` | Reports tree debt after a shell command changes Python |

Claude has no `TabWrite` tool. The Cursor `complexity-post` hook has no
equivalent here.

## The Bash hook

`make complexity-pre` reads the `Write` or `Edit` tool payload. A shell command
that writes Python sends no such payload. `sed -i`, a heredoc and `python -c`
thus get past the pre-hook. `scripts/hooks/post-bash.sh` closes that path.

The hook runs after each `Bash` call. It stops immediately if no `.py` file
changed since HEAD. If a `.py` file changed, it runs `make complexity-check`.
If the tree has debt, the hook exits 2 and sends the report to stderr. The
agent that made the write then sees the report.

`PostToolUse` runs after the tool completes. The hook thus reports a breach. It
cannot deny one. Only `Write` and `Edit` get denial before disk.

Three limits apply. Know them before you rely on this hook:

- A new `.py` file that git does not track is not measured. `make
  complexity-check` reads the git index. Stage the file, or write it with the
  `Write` tool, which the pre-hook covers.
- The report shows the debt of the whole tree. It does not show only the
  function you changed. `make complexity-pre` permits a breach that HEAD
  already has. This hook does not.
- The hook fails open if the guard stops with an error. A merge conflict makes
  the guard fail to parse the file. The hook then stays silent. Run `make
  check` after you solve a conflict.
