import assert from "node:assert/strict"
import test from "node:test"

import registerGithubWorkflowExtension, {
  isAllowedWorkflowCommand,
} from "../.pi/extensions/github-workflows.ts"

function registeredHandlers() {
  const handlers = new Map()
  registerGithubWorkflowExtension({
    on(event, handler) {
      handlers.set(event, handler)
    },
  })
  return handlers
}

function inputContext(notifications = []) {
  return {
    ui: {
      notify(message, level) {
        notifications.push({ message, level })
      },
    },
  }
}

function bashEvent(command) {
  return { toolName: "bash", input: { command } }
}

function commitMessage() {
  return [
    "git commit -F - <<'EOF'",
    "Add the GitHub workflow commands",
    "",
    "Preserve the project workflow in Pi.",
    "EOF",
  ].join("\n")
}

function pullRequestMessage() {
  return [
    'scripts/gh-exact pr create --title "Add the GitHub workflow commands" --body "$(cat <<\'EOF\'',
    "## Description",
    "Expose the repository workflows in Pi.",
    "",
    "## Key Changes",
    "- Preserve the commit workflow",
    "- Preserve the pull-request workflow",
    "- Enforce the source command boundaries",
    "EOF",
    ')" --assignee "$EXACT_GITHUB_USER"',
  ].join("\n")
}

test("test_explicit_commit_activation", async () => {
  const handlers = registeredHandlers()
  const input = handlers.get("input")
  const toolCall = handlers.get("tool_call")
  const settled = handlers.get("agent_settled")

  assert.equal(await toolCall(bashEvent("git status")), undefined)
  assert.deepEqual(await input({ text: "/commit", source: "interactive" }, inputContext()), {
    action: "continue",
  })
  assert.equal(await toolCall(bashEvent("git status")), undefined)
  assert.equal(
    (await toolCall({ toolName: "read", input: { path: "README.md" } })).block,
    true,
  )

  settled()
  assert.equal(await toolCall(bashEvent("git status")), undefined)
})

test("test_explicit_create_pr_activation", async () => {
  const handlers = registeredHandlers()
  const input = handlers.get("input")
  const toolCall = handlers.get("tool_call")
  const toolResult = handlers.get("tool_result")
  const settled = handlers.get("agent_settled")

  await input({ text: "/create-pr", source: "interactive" }, inputContext())
  assert.equal(await toolCall(bashEvent("git branch --show-current")), undefined)
  assert.equal(isAllowedWorkflowCommand("create-pr", pullRequestMessage()), true)
  await toolCall(bashEvent("git status --short"))
  toolResult({
    toolName: "bash",
    input: { command: "git status --short" },
    content: [{ type: "text", text: " M README.md" }],
    isError: false,
  })

  settled()
  await input({ text: "yes", source: "interactive" }, inputContext())
  assert.equal(await toolCall(bashEvent("git status --short")), undefined)
  assert.equal((await toolCall({ toolName: "read", input: {} })).block, true)
})

test("test_commit_allowlist_accepts_source_patterns", () => {
  const commands = [
    "git status",
    "git status --short",
    "git diff",
    "git add .pi/prompts/commit.md",
    "git reset HEAD",
    commitMessage(),
    "git log --oneline",
  ]

  for (const command of commands) {
    assert.equal(isAllowedWorkflowCommand("commit", command), true, command)
  }
})

test("test_create_pr_allowlist_accepts_source_patterns", () => {
  const commands = [
    "git branch --show-current",
    "git log --oneline",
    "git log -n 10 --oneline",
    "git log --oneline $(git merge-base HEAD origin/$DEFAULT_BRANCH)..HEAD",
    "git diff --stat $(git merge-base HEAD origin/$DEFAULT_BRANCH)..HEAD",
    "git diff --stat HEAD~10",
    "git status --short",
    "git status -sb",
    "git merge-base HEAD origin/main",
    "git rev-parse --abbrev-ref @{upstream} 2>/dev/null",
    "git push -u origin $BRANCH",
    "git push",
    "scripts/gh-exact repo view --json defaultBranchRef --jq '.defaultBranchRef.name'",
    pullRequestMessage(),
  ]

  for (const command of commands) {
    assert.equal(isAllowedWorkflowCommand("create-pr", command), true, command)
  }
})

test("test_global_account_switch_is_blocked", () => {
  const commands = [
    'gh auth switch -u "$EXACT_GITHUB_USER"',
    "gh api user --jq .login",
    "ORIGINAL_GH_USER=$(gh api user --jq .login 2>/dev/null)",
    '[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"',
  ]

  for (const command of commands) {
    assert.equal(isAllowedWorkflowCommand("commit", command), false, command)
    assert.equal(isAllowedWorkflowCommand("create-pr", command), false, command)
  }
})

test("test_create_pr_blocks_bare_gh", () => {
  const commands = [
    "gh pr view",
    "gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'",
    pullRequestMessage().replace("scripts/gh-exact pr create", "gh pr create"),
  ]

  for (const command of commands) {
    assert.equal(isAllowedWorkflowCommand("create-pr", command), false, command)
  }
})

test("test_commit_blocks_every_gh_call", () => {
  const commands = [
    "gh pr view",
    "scripts/gh-exact repo view --json defaultBranchRef --jq '.defaultBranchRef.name'",
    pullRequestMessage(),
  ]

  for (const command of commands) {
    assert.equal(isAllowedWorkflowCommand("commit", command), false, command)
  }
})

test("test_unauthorized_tool_and_command_are_blocked", () => {
  const commands = [
    "rm -rf .",
    "git status; rm -rf .",
    "git status && rm -rf .",
    "git diff $(rm -rf .)",
    "git status > /tmp/status",
    "git add -A",
    "git add .",
    "git add *.md",
    'git add "--all"',
    'git add "-A"',
    "git add '{foo,bar}'",
    "git add foo[ab]",
    "git reset --hard",
    "git commit --no-verify -m \"unsafe\"",
    "git push --force",
    "gh auth logout",
    "gh api user --method delete",
    "gh auth switch -u user; gh pr create",
  ]

  for (const command of commands) {
    assert.equal(isAllowedWorkflowCommand("commit", command), false, command)
    assert.equal(isAllowedWorkflowCommand("create-pr", command), false, command)
  }
})

test("test_heredoc_injection_is_blocked", () => {
  const injectedCommit = [
    "git commit -F - <<'EOF'",
    "$(rm -rf .)",
    "EOF",
  ].join("\n")
  const earlyDelimiter = [
    "git commit -F - <<'EOF'",
    "safe message",
    "EOF",
    "rm -rf .",
    "EOF",
  ].join("\n")
  const injectedPullRequest = [
    'scripts/gh-exact pr create --title "Safe title" --body "$(cat <<\'EOF\'',
    "$(rm -rf .)",
    "EOF",
    ')" --assignee "$EXACT_GITHUB_USER"',
  ].join("\n")

  assert.equal(isAllowedWorkflowCommand("commit", injectedCommit), false)
  assert.equal(isAllowedWorkflowCommand("commit", earlyDelimiter), false)
  assert.equal(isAllowedWorkflowCommand("create-pr", injectedPullRequest), false)
})

test("test_unauthorized_compound_command_is_blocked", async () => {
  const handlers = registeredHandlers()
  const input = handlers.get("input")
  const toolCall = handlers.get("tool_call")

  await input({ text: "/commit", source: "interactive" }, inputContext())
  assert.equal((await toolCall(bashEvent("git status && rm -rf ."))).block, true)
  assert.equal((await toolCall(bashEvent("git status; git diff"))).block, true)
  assert.equal((await toolCall({ toolName: "write", input: {} })).block, true)
})

test("test_argumentful_invocations_are_rejected", async () => {
  const handlers = registeredHandlers()
  const input = handlers.get("input")
  const toolCall = handlers.get("tool_call")
  const notifications = []

  assert.deepEqual(
    await input({ text: "/commit extra", source: "interactive" }, inputContext(notifications)),
    { action: "handled" },
  )
  assert.equal(notifications[0].level, "error")
  assert.equal(await toolCall(bashEvent("git status")), undefined)

  assert.deepEqual(
    await input({ text: "/create-pr extra", source: "interactive" }, inputContext(notifications)),
    { action: "handled" },
  )
  assert.equal(notifications.length, 2)
})
