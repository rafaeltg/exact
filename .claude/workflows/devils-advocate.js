// SYNC: pairs with .claude/commands/devils-advocate.md — the command owns input parsing
// (incl. question mode), the citation pass, verdict formula, report rendering, and the severity
// tier names; this script owns the framing agent, lens prompts, rule blocks, the severity
// DEFINITIONS (in sharedContext), schemas, fan-out, and synthesis. Edit severity labels together.
export const meta = {
  name: 'devils-advocate',
  description: 'Framing brief -> parallel adversarial lenses -> synthesis; returns hardening findings + calibration',
  phases: [
    { title: 'Framing', detail: 'extract the allow-list of what the doc already addresses' },
    { title: 'Lenses', detail: '6 adversarial lenses + conditional domain critic' },
    { title: 'Synthesize', detail: 'drop addressed, dedupe cross-lens, cap 15, calibration' },
  ],
}

// args: { documentText? | documentPath?, subject, sourcePath, inputKind,
//         domainSkillMap: [{ pattern: string, skill: string }] }  // regex source strings, repo-supplied
// The document arrives EITHER inline (documentText, <= 2,500 B) OR as a path the agents Read
// (documentPath) — the size-based sidecar rule in .claude/workflows/AGENTS.md. Which one is
// decided by KEY PRESENCE, never by a separate flag: a flag can disagree with the payload and
// used to ship the agents "DOCUMENT TEXT: undefined" whenever it was omitted or mistyped.
// `subject` is a bounded first-line summary (<= 200 B) the script needs when framing fails;
// it exists precisely so the script never has to hold the document text itself.
// ARGS TRANSIT CONTRACT — canonical in .claude/workflows/AGENTS.md. This preamble is
// duplicated verbatim in all five workflow scripts BY NECESSITY, not by oversight: workflow
// scripts are self-contained and the runtime cannot load a shared module. Do not "DRY" it out.
let A
try {
  A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
} catch (e) {
  const n = typeof args === 'string' ? args.length : 0
  throw new Error(
    `args failed to parse (${e.message}). Received ${n} chars. The Workflow tool SIZE-CAPS the ` +
    `args string and truncates mid-string; the recovery echo shows it complete even so. ` +
    `Pass large artifacts by FILE PATH, not inline text — see .claude/workflows/AGENTS.md.`,
  )
}
for (const [k, v] of Object.entries(A)) {
  if (typeof v === 'string' && v.length > 8000) {
    log(`WARNING: args.${k} is ${v.length} chars (>8000) — pass it by path instead (.claude/workflows/AGENTS.md)`)
  }
}
// Not redundant with the loop above: that one inspects only string values, so it cannot see
// domainSkillMap (an array of objects).
const argsTotal = typeof args === 'string' ? args.length : JSON.stringify(A).length
if (argsTotal > 12000) {
  log(`WARNING: args total ${argsTotal} chars (>12000 tripwire) — see .claude/workflows/AGENTS.md`)
}

// Model policy (deliberate, tunable — this workflow deviates from bug-bash.js/
// forensic-review.js's sonnet-fan-out/session-model-synth default):
// - lens agents: pinned 'opus' @ effort 'high' — adversarial-idea-hardening is a
//   generative reasoning task (constructing falsifiable scenarios, alternatives, second-
//   order effects), not a recall-over-a-fixed-checklist scan; the stronger model is
//   spent here to reduce missed findings (synthesis and the citation pass only catch
//   false positives among what a lens proposes, never what it failed to propose).
// - synthesizer: pinned 'opus' @ effort 'high' — dedup/severity/drop judgments are the
//   quality bottleneck; worth top-tier regardless of session model.
// agentType is 'readonly-worker' (.claude/agents/readonly-worker.md), not the built-in
// 'general-purpose' — same reasoning capability, but no Write/Edit/NotebookEdit/Artifact/
// Bash grant, so the "MUST NOT modify any file" rule in every lens prompt is enforced by
// the harness, not just by instruction.
const LENS = { model: 'opus', effort: 'high', agentType: 'readonly-worker' }
const SYNTH = { model: 'opus', effort: 'high', agentType: 'readonly-worker' }

// Severity DEFINITIONS live here (interpolated into sharedContext so every lens is anchored).
// The paired .md keeps only the tier NAMES + the verdict formula + the design-intent
// parenthetical and points here. Edit both together.
const SEVERITY_DEFINITIONS = `SEVERITY — grounded in impact on viability and likelihood given stated context.
- critical — A concrete gap, false premise, or unaddressed failure mode that would likely cause the initiative to fail, force a fundamental rethink, or create irreversible damage if not addressed before implementation. Specific scenario, realistic trigger.
- major — A meaningful blind spot, underexplored trade-off, or missing contingency that would cause significant rework or operational pain if discovered mid-implementation. Addressable without rethinking the core approach.
- minor — A useful perspective, open question, or hardening opportunity that improves robustness but whose absence would not derail implementation.`

const FRAMING_SCHEMA = {
  type: 'object',
  required: ['subject', 'artifact_type', 'stated_goals', 'stated_assumptions', 'stated_constraints', 'stated_alternatives_considered', 'stated_non_goals', 'stated_success_criteria', 'risks_already_discussed', 'domains'],
  additionalProperties: false,
  properties: {
    subject: { type: 'string' },
    artifact_type: { type: 'string', enum: ['spec', 'design', 'plan', 'rfc', 'proposal', 'postmortem', 'architecture', 'migration', 'runbook', 'idea', 'other'] },
    stated_goals: { type: 'array', items: { type: 'string' } },
    stated_assumptions: { type: 'array', items: { type: 'string' } },
    stated_constraints: { type: 'array', items: { type: 'string' } },
    stated_alternatives_considered: { type: 'array', items: { type: 'string' } },
    stated_non_goals: { type: 'array', items: { type: 'string' } },
    stated_success_criteria: { type: 'array', items: { type: 'string' } },
    risks_already_discussed: { type: 'array', items: { type: 'string' } },
    domains: { type: 'array', items: { type: 'string' } },
  },
}

const FINDING_ITEM = {
  type: 'object',
  required: ['lens', 'kind', 'severity', 'title', 'doc_anchor', 'argument', 'suggestion'],
  additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    kind: { type: 'string', enum: ['concern', 'open_question', 'alternative', 'hardening_suggestion'] },
    severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
    title: { type: 'string', description: '<= 80 chars' },
    doc_anchor: { type: 'string', description: "verbatim quote from the document, or 'not addressed' (alternative/open_question only)" },
    argument: { type: 'string', description: 'concrete falsifiable scenario, <= 400 chars' },
    suggestion: { type: 'string', description: '1-3 sentences, never a code edit' },
  },
}

// fragile_point is PRESENCE-GATED (absent from properties for the alternative lens) rather
// than conditionally-required like premortem: with additionalProperties:false the harness
// then REJECTS an alternative lens that emits it — that lens's empty findings array is a
// positive signal the fallback must not dilute. premortem keeps its older
// conditionally-required shape deliberately; do not harmonize the two.
const lensSchema = ({ premortem, fragile }) => ({
  type: 'object',
  required: ['findings', 'calibration'],
  additionalProperties: false,
  properties: {
    findings: { type: 'array', items: FINDING_ITEM },
    calibration: {
      type: 'object',
      required: [
        'least_confident',
        ...(premortem ? ['premortem'] : []),
        ...(fragile ? ['fragile_point'] : []),
      ],
      additionalProperties: false,
      properties: {
        least_confident: { type: 'string', description: "one sentence — which of your findings you are least confident in and why; 'n/a' if no findings" },
        premortem: { type: 'string', description: 'exactly one sentence — shipped 3 months ago, now on fire: the single most likely cause and the missing sentence that would have prevented it' },
        ...(fragile ? { fragile_point: { type: 'string', description: "exactly one sentence — when findings is empty: the single most fragile assumption the document makes within this lens's scope; 'n/a' when findings is non-empty" } } : {}),
      },
    },
  },
})

const SYNTH_SCHEMA = {
  type: 'object',
  required: ['findings', 'calibration'],
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['lens', 'lenses', 'section', 'kind', 'severity', 'title', 'doc_anchor', 'argument', 'suggestion'],
        additionalProperties: false,
        properties: {
          ...FINDING_ITEM.properties,
          lenses: { type: 'array', items: { type: 'string' } },
          section: { type: 'string', enum: ['Premises Worth Re-examining', 'Failure Modes Not Discussed', 'Operational Realities', 'Alternatives Worth Considering', 'Second-Order Effects', 'Reversibility & Rollback', 'Domain-Specific Concerns', 'Open Questions'] },
        },
      },
    },
    calibration: {
      type: 'object',
      required: ['least_confident', 'premortem'],
      additionalProperties: false,
      properties: { least_confident: { type: 'string' }, premortem: { type: 'string' } },
    },
  },
}

// REQUIRED ARGS — throw, do not warn: without the document every agent reviews nothing and the
// run still completes, returning confident findings about an empty prompt. That is the same
// failure class as the truncated-args parse above, so it gets the same fail-fast treatment.
// (This check is per-script and sits AFTER the verbatim shared preamble, which stays identical
// across all five scripts.)
const hasDocPath = typeof A.documentPath === 'string' && A.documentPath.length > 0
const hasDocText = typeof A.documentText === 'string' && A.documentText.length > 0
if (!hasDocPath && !hasDocText) {
  throw new Error(
    `args carries neither documentText nor documentPath. One is required — pass documentText ` +
    `for a document at or under 2,500 bytes, documentPath otherwise ` +
    `(.claude/workflows/AGENTS.md, sidecar rule). ` +
    `Received keys: ${Object.keys(A).join(', ') || '(none)'}.`,
  )
}
if (hasDocPath && hasDocText) {
  log('WARNING: args carries BOTH documentText and documentPath — using documentPath (the copy with no size bound)')
}

// The document reaches every agent one of two ways and never both: inline when the orchestrator
// judged it small enough, otherwise as a path to Read (.claude/workflows/AGENTS.md, sidecar
// rule). Both branches produce the same labelled block, so no prompt below needs to branch.
const documentBlock = hasDocPath
  ? `DOCUMENT — read it before anything else:
Read the file at ${A.documentPath}. Its contents ARE "the document" that every instruction here
refers to. Read it COMPLETELY: Read truncates at 2,000 lines by default, so page with \`offset\`
until you reach the end. A partially-read document turns "the doc does not address X" into a
false finding, which is the exact failure this review is supposed to avoid.`
  : `DOCUMENT TEXT:\n\n${A.documentText}`

phase('Framing')
const framing = await agent(
  `You are the framing analyst for a devil's-advocate review. Read the document and extract what the author has already stated, decided, or acknowledged. Your output is an allow-list — anything the document already covers must NOT be re-flagged by the lens agents downstream.

${documentBlock}

Extract, using verbatim phrases or close paraphrases (empty array where the doc is silent): subject (one line); artifact_type; stated_goals; stated_assumptions; stated_constraints; stated_alternatives_considered (with rejection reasoning if stated); stated_non_goals; stated_success_criteria; risks_already_discussed; domains (technical domains with substantive coverage, e.g. database, backend, infra, security, api-design, data-pipeline, observability).`,
  { label: 'framing', phase: 'Framing', schema: FRAMING_SCHEMA, ...LENS },
)

// Fallback subject comes from the bounded `subject` arg, never from the document text — the
// text is not guaranteed to be in-process at all (sidecar rule).
const FRAMING_BRIEF = framing ?? {
  subject: A.subject ?? A.sourcePath ?? 'untitled document',
  artifact_type: 'other',
  stated_goals: [], stated_assumptions: [], stated_constraints: [],
  stated_alternatives_considered: [], stated_non_goals: [],
  stated_success_criteria: [], risks_already_discussed: [], domains: [],
}
const framingFailed = framing == null

// Domain agent selection from the brief's domains. The regex->skill map is repo-supplied
// (D4): the command passes domainSkillMap as [{pattern, skill}] regex source strings so this
// script carries zero repo-specific content. Defaults to [] when the arg is absent.
const domainSkillMap = (A.domainSkillMap ?? []).map((m) => [new RegExp(m.pattern, 'i'), m.skill])
const domainSkills = [...new Set(
  FRAMING_BRIEF.domains.flatMap((d) => domainSkillMap.filter(([re]) => re.test(d)).map(([, s]) => s)),
)]

const sharedContext = `You are one adversarial lens in a devil's-advocate review. Find blind spots, do not tear the idea down. Every finding ends with a specific, actionable suggestion.

SOURCE: ${A.sourcePath}  (kind: ${A.inputKind})

${documentBlock}

FRAMING BRIEF (what the document already addresses — do NOT re-flag these):

${JSON.stringify(FRAMING_BRIEF, null, 1)}

DISCIPLINE BAR — every finding: (1) verbatim doc_anchor quote, OR "not addressed" for alternative/open_question kinds only; (2) concrete falsifiable argument <= 400 chars; (3) constructive suggestion, 1-3 sentences, never a code edit; (4) not already in the framing brief.

${SEVERITY_DEFINITIONS}

ANTI-FUD — discard: bikeshedding; scope creep (its own non-goals); restated self-criticism; vague hand-waving (no trigger/threshold); theoretical (no constructible situation); hindsight bias (alternative exists != current choice wrong); credential gatekeeping (no doc evidence); redundant alternative (already rejected with reasoning).

ADVERSARIAL DISCIPLINE — before submitting: construct the strongest defense the author could make; can you defeat it with evidence from the doc? Is the scenario realistic given stated constraints? Would the author learn something new, or say "already thought about that"? If you cannot state a concrete trigger in one sentence, drop it.

You may Read/Grep/Glob files the document references. You may WebSearch/WebFetch for prior-art research — prefer official documentation over blogs, and note the version/date where determinable — but you MUST cite the URL in argument and extract a concrete lesson (not "see this link"); do not fabricate URLs. MUST NOT modify any file. Read-only.

Cap at 10 findings, prioritized by severity then how much the author would learn. Quality over quantity. Nothing worth flagging => empty findings array. Your calibration.least_confident names the finding you are least sure of and why ("n/a" if none). If your findings array is empty, calibration.fragile_point MUST name — in exactly one sentence — the single most fragile assumption the document makes within your lens's scope: zero findings means nothing cleared the discipline bar, not that nothing is fragile. When you have findings, set fragile_point to "n/a". (The alternative lens is exempt — its own instructions apply.)`

const LENS_PROMPTS = {
  premise: `${sharedContext}

Your lens id: "premise". MINDSET: "Every belief this document treats as given is a claim I have not yet seen evidence for." Challenge implicit beliefs and unstated assumptions: unvalidated premises ("users will adopt", "the system handles X traffic") without evidence; hidden dependencies treated as certain but actually contingent (a service, a team's agreement, a vendor SLA); survivorship reasoning ("Company X did it") ignoring context differences; anchoring on the current state without projecting the plan's own success scenario; correlation-as-causation. For each, state what breaks if the premise is wrong.`,

  failure: `${sharedContext}

Your lens id: "failure". MINDSET: "I am the production incident this document did not plan for, looking for my way in." Map failure modes the doc omits: partial failure (one component down — degraded mode or cascade?); adversarial/malformed input (does it assume cooperative users?); scale corners (0, 1, 10x, the memory boundary); timing/ordering (out-of-order events, retries, concurrent actors on one resource); dependency failure (external service unavailable/slow/wrong); rollback under failure (state if a migration/deploy/backfill dies partway — recoverable?). Each names a concrete trigger and a specific downstream consequence.

MANDATORY PRE-MORTEM: your calibration object MUST carry "premortem": exactly one sentence — assume this shipped 3 months ago and is now on fire; walking backwards from the postmortem, name the single most likely cause and the doc's missing sentence that would have prevented it. Required even if you return no findings.`,

  operational: `${sharedContext}

Your lens id: "operational". MINDSET: "I am the on-call engineer at 3 AM a year from now, with none of the author's context." Evaluate life after launch: 3 AM incident (can on-call diagnose from logs/metrics/dashboards alone, or do failures look alike?); day-30 onboarding (can a new hire modify/deploy without tribal knowledge — what runbooks/ADRs are missing?); day-365 maintenance (dependency upgrades, team rotation — self-documenting or reliant on memory?); deploy friction and rollback procedure; observability gaps (metrics/logs/traces/alerts specified or assumed?); migration/transition costs (parallel-run duration, cutover risk). Ground each in a specific operational scenario, not "best practices."`,

  alternative: `${sharedContext}

Your lens id: "alternative". MINDSET: "The chosen approach is the one that arrived first, not necessarily the one that would win the argument." Propose 1-3 genuinely different approaches the doc didn't consider (or only superficially): different architecture, buy-vs-build, work sequencing, or abstraction — not a minor variation. Always test the null alternative first: doing nothing / keeping the status quo, or deferring until named missing data exists — if the document never establishes why acting now beats not acting, that is a finding. Each states its honest trade-off (what you gain AND lose), is feasible under the doc's stated constraints, and gets a one-line case for why it's worth considering. If the doc already made a well-reasoned choice among strong alternatives — and justifies acting at all — return an empty findings array — that is a positive signal, not a failure. Use kind "alternative", doc_anchor "not addressed"; suggestion = "Consider evaluating [alternative] against [current approach] on [dimension] before committing." Your calibration schema has no fragile_point field — do not emit one. For this lens an empty findings array is a complete, positive answer, not silence.`,

  'second-order': `${sharedContext}

Your lens id: "second-order". MINDSET: "Nothing ships in isolation — I trace the ripples the author stopped tracing." Trace downstream/indirect effects one or two steps out: adjacent-team impact (another team's API/data model/pipeline/on-call — aware and aligned?); contract changes (public API/event schema/message format — which consumers, in what order?); organizational coupling (new cross-team dependency, approval workflow, ownership change); technical-debt dynamics (pays down or creates debt — conscious and documented?); vendor/platform lock-in and switching cost; hiring/skill implications. Focus on plausible, consequential effects.`,

  reversibility: `${sharedContext}

Your lens id: "reversibility". MINDSET: "Assume the author is wrong about something important; my job is to price the cost of discovering that late." Identify one-way doors and the cost of being wrong: irreversible decisions (data-losing migrations, public API contracts, org restructuring, vendor lock-in, deletions, published formats); the concrete cost if the author's assumptions are wrong (time, money, trust, data, morale); a missing pilot/canary/feature-flag path (could this be validated incrementally — if not, why?); the rollback story and time-to-revert; the blast radius vs. the confidence level. For each one-way door, suggest a way to make it more reversible, or what additional validation to do before committing.`,
}

phase('Lenses')
const specs = Object.entries(LENS_PROMPTS).map(([id, prompt]) => ({
  label: id,
  prompt,
  schema: lensSchema({ premortem: id === 'failure', fragile: id !== 'alternative' }),
}))

if (domainSkills.length > 0) {
  specs.push({
    label: 'domain',
    schema: lensSchema({ premortem: false, fragile: true }),
    prompt: `${sharedContext}

Your lens id: "domain". MINDSET: "I am the specialist reviewer this document never had." Load these reviewer skills from .claude/skills/: ${domainSkills.join(', ')} (read each skill's SKILL.md and follow it).

Apply each skill's review methodology to the document's claims and technical approach within that domain. Surface domain-specific blind spots the universal lenses would miss for lack of specialized knowledge (e.g. graph-topology and state-shape assumptions; retrieval-failure and citation-resolution gaps; test isolation and fake-vs-real seams; abstraction leaks and domain-boundary confusion). Apply the discipline bar and anti-FUD rules; do not duplicate the universal lenses.`,
  })
}

const results = await parallel(specs.map((s) => () =>
  agent(s.prompt, { label: s.label, phase: 'Lenses', schema: s.schema, ...LENS })))

const agentsFailed = specs.filter((s, i) => results[i] == null).map((s) => s.label)
if (framingFailed) agentsFailed.unshift('framing')

const allFindings = []
const lensCalibrations = []
let premortem = null
results.forEach((r, i) => {
  if (r == null) return
  allFindings.push(...r.findings)
  lensCalibrations.push({ lens: specs[i].label, ...r.calibration })
  if (specs[i].label === 'failure' && r.calibration.premortem) premortem = r.calibration.premortem
})
const lensesEmpty = specs.filter((s, i) => results[i] != null && results[i].findings.length === 0).map((s) => s.label)

// Empty-lens fallback statements (exempt: alternative — its empty result is a positive signal).
const fragilePoints = specs
  .map((s, i) => ({ lens: s.label, r: results[i] }))
  .filter(({ lens, r }) => lens !== 'alternative' && r != null && r.findings.length === 0
    && typeof r.calibration.fragile_point === 'string' && r.calibration.fragile_point !== 'n/a')
  .map(({ lens, r }) => ({ lens, fragile_point: r.calibration.fragile_point }))

const base = {
  framingBrief: FRAMING_BRIEF,
  domainSkills,
  lensesEmpty,
  fragilePoints,
  agentsFailed,
}

if (allFindings.length === 0) {
  return {
    findings: [],
    calibration: { least_confident: 'n/a', premortem: premortem ?? 'n/a' },
    ...base,
  }
}

phase('Synthesize')
log(`${allFindings.length} raw findings from ${specs.length - agentsFailed.length} lenses — synthesizing`)

// Cross-lens convergence is an ORDERING/ANNOTATION signal, never a severity promotion:
// severity tiers are impact-anchored and the paired .md's verdict formula is calibrated to
// them, so a consensus bump would silently recalibrate verdicts. Do not add a promotion rule.
const synth = await agent(
  `You are the synthesizer for a devil's-advocate review.

Framing brief (allow-list — anything overlapping is a drop):

${JSON.stringify(FRAMING_BRIEF, null, 1)}

Raw findings:

${JSON.stringify(allFindings, null, 1)}

Per-lens calibration statements (for task 6):

${JSON.stringify(lensCalibrations, null, 1)}

Tasks: (1) Drop already-addressed findings whose doc_anchor/argument overlaps semantically with the brief's risks_already_discussed, stated_assumptions, stated_non_goals, or stated_alternatives_considered. (2) Deduplicate cross-lens — when agents argue the same underlying point from different lenses, merge into one, keeping the strongest argument/suggestion and highest severity, and record all contributing lenses in the lenses array (single-lens findings get a one-element array). (3) Re-apply discipline — drop anything vague, bikeshedding, scope-creeping, unable to state a one-sentence trigger, or citing a URL without a concrete lesson. (4) Cap at 15, sorted by severity (critical -> major -> minor); within one severity tier, place findings whose lenses array has more than one entry first, more lenses first; NEVER change a finding's severity because several lenses flagged it — severity measures impact, convergence measures confidence, and convergence is expressed only by this ordering and the lenses array; no single lens contributes more than 5 survivors (demote a dominating lens's weakest). (5) Assign each survivor a section by primary lens: premise -> "Premises Worth Re-examining"; failure -> "Failure Modes Not Discussed"; operational -> "Operational Realities"; alternative -> "Alternatives Worth Considering"; second-order -> "Second-Order Effects"; reversibility -> "Reversibility & Rollback"; domain -> "Domain-Specific Concerns"; any open_question kind -> "Open Questions". (6) Build the calibration summary: least_confident = the single strongest least-confident statement among surviving findings' lenses, attributed as "lens: sentence"; premortem = the failure lens's premortem sentence, verbatim or tightened to one sentence — never averaged with anything else${premortem ? ` (it was: ${JSON.stringify(premortem)})` : ''}.`,
  { label: 'synthesizer', phase: 'Synthesize', schema: SYNTH_SCHEMA, ...SYNTH },
)

if (synth == null) {
  return {
    findings: [],
    calibration: { least_confident: 'n/a', premortem: premortem ?? 'n/a' },
    ...base,
    agentsFailed: [...agentsFailed, 'synthesizer'],
  }
}

return { findings: synth.findings, calibration: synth.calibration, ...base }
