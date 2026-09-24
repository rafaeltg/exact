import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"

export type Workflow = "commit" | "create-pr"

const STDERR_REDIRECT = " 2>/dev/null"
const KNOWN_VARIABLES = /\$(?:EXACT_GITHUB_USER|BRANCH|DEFAULT_BRANCH)\b/g
const SHELL_OPERATORS = /[;&|<>`()\\]|\r|\n/
const COMMIT_HEREDOC = /^git commit -F - <<'EOF'\r?\n([\s\S]*)\r?\nEOF$/
const PR_CREATE_HEREDOC =
  /^scripts\/gh-exact pr create --title "[^"$`\r\n]*" --body "\$\(cat <<'EOF'\r?\n([\s\S]*)\r?\nEOF\r?\n\)" --assignee "\$EXACT_GITHUB_USER"$/
const BRANCH_HISTORY =
  /^git (?:log --oneline|diff --stat) \$\(git merge-base HEAD origin\/\$DEFAULT_BRANCH\)\.\.HEAD$/
const MERGE_BASE = /^git merge-base HEAD origin\/[A-Za-z0-9._/-]+$/
const GIT_ADD_PATH = /^(?!-)(?!\.\.?$)[^\s;&|<>`$()*?\[\]{}!]+$/

const SIMPLE_COMMANDS: Record<Workflow, readonly RegExp[]> = {
  commit: [
    /^git status(?: --short)?$/,
    /^git diff$/,
    /^git reset HEAD$/,
    /^git log(?: --oneline)?$/,
    /^git commit$/,
    /^git commit -m "[^"$`;&|<>()[\]\r\n]+"$/,
  ],
  "create-pr": [
    /^git branch --show-current$/,
    /^git log(?: --oneline| -n 10 --oneline)?$/,
    /^git diff(?: --stat)?$/,
    /^git diff --stat HEAD~10$/,
    /^git status(?: --short| -sb)?$/,
    /^git rev-parse --abbrev-ref @\{upstream\}$/,
    /^git push$/,
    /^git push -u origin \$BRANCH$/,
    /^scripts\/gh-exact repo view --json defaultBranchRef --jq '\.defaultBranchRef\.name'$/,
  ],
}

function hasOnlyKnownVariables(command: string): boolean {
  return !command.replace(KNOWN_VARIABLES, "").includes("$")
}

function safeHeredocBody(body: string): boolean {
  return !/[`$]/.test(body) && !/(^|\r?\n)EOF(\r?\n|$)/.test(body)
}

function isSafeGitAdd(command: string): boolean {
  if (!command.startsWith("git add ") || /['"]/.test(command)) return false
  const paths = command.slice("git add ".length).split(/\s+/)
  return paths.length > 0 && paths.every((path) => GIT_ADD_PATH.test(path))
}

function isSimpleAllowedCommand(workflow: Workflow, command: string): boolean {
  if (command !== command.trim()) return false
  const commandWithoutRedirect = command.endsWith(STDERR_REDIRECT)
    ? command.slice(0, -STDERR_REDIRECT.length)
    : command
  if (SHELL_OPERATORS.test(commandWithoutRedirect)) return false
  if (!hasOnlyKnownVariables(commandWithoutRedirect)) return false
  if (workflow === "commit" && isSafeGitAdd(commandWithoutRedirect)) return true
  if (workflow === "create-pr" && MERGE_BASE.test(commandWithoutRedirect)) return true
  return SIMPLE_COMMANDS[workflow].some((pattern) => pattern.test(commandWithoutRedirect))
}

function isSpecialAllowedCommand(workflow: Workflow, command: string): boolean {
  const commit = command.match(COMMIT_HEREDOC)
  if (workflow === "commit" && commit) return safeHeredocBody(commit[1])
  const pullRequest = command.match(PR_CREATE_HEREDOC)
  if (workflow === "create-pr" && pullRequest) return safeHeredocBody(pullRequest[1])
  return workflow === "create-pr" && BRANCH_HISTORY.test(command)
}

export function isAllowedWorkflowCommand(workflow: Workflow, command: string): boolean {
  return isSpecialAllowedCommand(workflow, command) || isSimpleAllowedCommand(workflow, command)
}

function invocationWorkflow(text: string): Workflow | undefined {
  if (text === "/commit") return "commit"
  if (text === "/create-pr") return "create-pr"
  return undefined
}

function hasWorkflowArguments(text: string): boolean {
  return /^\/(?:commit|create-pr)\s+/.test(text)
}

function isProceedConfirmation(text: string): boolean {
  return /^(?:yes|y|proceed|continue|go ahead)[!., ]*$/i.test(text)
}

function hasTextContent(content: unknown): boolean {
  if (typeof content === "string") return content.trim() !== ""
  if (!Array.isArray(content)) return false
  return content.some((part) => {
    if (!part || typeof part !== "object" || !("text" in part)) return false
    const text = part.text
    return typeof text === "string" && text.trim() !== ""
  })
}

function clearWorkflow(state: {
  active?: Workflow
  pending?: Workflow
  confirmationPending?: boolean
}): void {
  state.active = undefined
  state.pending = undefined
  state.confirmationPending = false
}

export default function registerGithubWorkflowExtension(pi: ExtensionAPI): void {
  const state: {
    active?: Workflow
    pending?: Workflow
    confirmationPending?: boolean
  } = {}

  pi.on("input", (event, ctx) => {
    if (event.source === "extension") return { action: "continue" }

    const text = event.text.trim()
    const workflow = invocationWorkflow(text)
    if (workflow) {
      state.active = workflow
      state.pending = undefined
      state.confirmationPending = false
      return { action: "continue" }
    }

    if (hasWorkflowArguments(text)) {
      clearWorkflow(state)
      ctx.ui.notify("/commit and /create-pr do not accept arguments", "error")
      return { action: "handled" }
    }

    if (state.pending) {
      const pending = state.pending
      state.pending = undefined
      if (isProceedConfirmation(text)) {
        state.active = pending
        state.confirmationPending = false
      }
    }

    return { action: "continue" }
  })

  pi.on("tool_call", async (event) => {
    const workflow = state.active
    if (!workflow) return

    if (event.toolName !== "bash") {
      return { block: true, reason: `/${workflow} permits Bash Git and GitHub CLI calls only` }
    }

    const input = event.input as { command?: unknown }
    if (typeof input.command !== "string" || !isAllowedWorkflowCommand(workflow, input.command)) {
      return { block: true, reason: `Command is outside the /${workflow} allowlist` }
    }
  })

  pi.on("tool_result", (event) => {
    if (state.active !== "create-pr" || event.toolName !== "bash" || event.isError) return
    const input = event.input as { command?: unknown }
    if (input.command === "git status --short" && hasTextContent(event.content)) {
      state.confirmationPending = true
    }
  })

  pi.on("agent_settled", () => {
    state.pending = state.confirmationPending ? "create-pr" : undefined
    state.active = undefined
    state.confirmationPending = false
  })
  pi.on("session_shutdown", () => clearWorkflow(state))
}
