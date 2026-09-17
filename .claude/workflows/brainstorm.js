// SYNC: pairs with .claude/commands/brainstorm.md — the command owns input acquisition
// (parse args, read/size-check a context file, slug + timestamp + seed) and report rendering
// (inline primary + file secondary); this script owns classification (problem kind, depth,
// frame/idea counts, grounding decision), the frames table, context gathering, diverge/focus
// fan-out, scoring weights, deterministic post-scoring, schemas, and the isolation invariant.
export const meta = {
  name: 'brainstorm',
  description: 'Parallel divergent ideation: context → diverge (N frames) → score & cluster → deepen top 3',
  phases: [
    { title: 'Context', detail: 'gather codebase context for code-shaped problems (conditional)' },
    { title: 'Diverge', detail: 'N isolated cognitive frames, M ideas each — no evaluation allowed' },
    { title: 'Score & Cluster', detail: 'rate novelty/viability/fit, cluster by angle, prune traps, shortlist' },
    { title: 'Deepen', detail: 'sketch top 3 survivors with risks, first steps, and child ideas' },
  ],
}

// args: { problemStatement (<= 1,500 B), contextFile? (<= 1,500 B), contextFilePath?, seed }
//   (classification — problemKind, depth, frameCount, ideasPerFrame, gatherCodeContext —
//    is computed below by classify(), not passed in.)
// problemStatement is capped, not sidecarred: classify() consumes it in-process, and scripts
// cannot read files (.claude/workflows/AGENTS.md § Authoring notes).
// contextFile is capped at 1,500 bytes by the paired .md — this script never uses more, and
// args is size-capped (.claude/workflows/AGENTS.md). The slice below is belt-and-braces; the
// full file remains reachable to agents via contextFilePath.
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
// any non-string field added to this payload later.
const argsTotal = typeof args === 'string' ? args.length : JSON.stringify(A).length
if (argsTotal > 12000) {
  log(`WARNING: args total ${argsTotal} chars (>12000 tripwire) — see .claude/workflows/AGENTS.md`)
}

// Classification is deterministic string logic — owned by the script, not the
// orchestrating model. The command passes only the raw problem + optional file + seed.
const { problemKind, depth, frameCount, ideasPerFrame, gatherCodeContext } =
  classify(A.problemStatement ?? '', Boolean(A.contextFile))

// ─── Model policy ───────────────────────────────────────────────────────────
// Diverge agents: opus/high — the core value proposition. Pushing past the obvious
// requires maximum model capability. Cost is justified because every run is an explicit
// human decision (the command sets disable-model-invocation: true; no auto-invocation).
// Scorer: opus/high — quality judgment is the bottleneck; traps and provocation need it.
// Deepeners: opus/medium — connecting dots, not breaking new ground.
// Context: sonnet/medium — just codebase navigation, not reasoning.
const CONTEXT = { model: 'sonnet', effort: 'medium', agentType: 'readonly-worker' }
const DIVERGE = { model: 'opus', effort: 'high', agentType: 'readonly-worker' }
const SCORER = { model: 'opus', effort: 'high', agentType: 'readonly-worker' }
const DEEPEN = { model: 'opus', effort: 'medium', agentType: 'readonly-worker' }

// ─── Frames table ───────────────────────────────────────────────────────────
// Each frame has: id, name, vantage (the prompt the diverge agent receives), tags.
// Tags: code, design, general, wild. Frame selection uses tags + problemKind.
const FRAMES = [
  {
    id: 'hardware_engineer',
    name: 'hardware engineer',
    vantage: 'You think in latency, memory layout, and physical constraints. Re-ask this as a hardware/firmware problem. What does the bus topology, cache hierarchy, timing budget, or signal integrity tell you about solutions?',
    tags: ['code', 'wild'],
  },
  {
    id: 'regulator',
    name: 'regulator',
    vantage: 'You audit systems for compliance, failure modes, and accountability. What must be provable, traceable, auditable, or refusable here? What would a regulator demand you demonstrate?',
    tags: ['design', 'general'],
  },
  {
    id: 'ten_year_old',
    name: '10-year-old',
    vantage: 'You are a curious 10-year-old who has never seen software. Describe naive but unencumbered approaches. Ignore convention, jargon, and "the way it is done." Ask why not.',
    tags: ['general', 'wild'],
  },
  {
    id: 'attacker',
    name: 'competitor trying to break it',
    vantage: 'You are a hostile competitor or attacker. Generate approaches that exploit, fail, or sabotage the obvious solution. Then invert each attack into a constructive idea — if X breaks it, what would make X impossible?',
    tags: ['code', 'design'],
  },
  {
    id: 'biology',
    name: 'biology',
    vantage: 'Transplant a mechanism from biology: immune systems, neural plasticity, cell signaling, evolution, gut flora, swarm intelligence, apoptosis. Force-fit it onto this engineering problem — what is the analogue?',
    tags: ['code', 'wild'],
  },
  {
    id: 'logistics',
    name: 'logistics',
    vantage: 'Steal mechanisms from logistics: queues, batching, just-in-time, hub-and-spoke, returns, last-mile delivery, consolidation, cross-docking. Apply them literally to data/request/user flows.',
    tags: ['code', 'design'],
  },
  {
    id: 'game_design',
    name: 'game design',
    vantage: 'Approach this as a game designer. What are the loops, rewards, friction points, save-states, difficulty curves, speedrun tricks? Treat the user (or developer, or operator) as a player.',
    tags: ['design', 'general'],
  },
  {
    id: 'markets',
    name: 'markets',
    vantage: 'Treat the problem as a market. Buyers, sellers, market-makers, information asymmetry. What does an auction, a futures contract, a clearing house, or a price signal look like here?',
    tags: ['design', 'wild'],
  },
  {
    id: 'inversion',
    name: 'inversion',
    vantage: 'Ask the OPPOSITE question. If the goal is X, brainstorm how to guarantee NOT X — make it fail spectacularly. Then negate each failure mode back into an idea.',
    tags: ['code', 'design', 'general'],
  },
  {
    id: 'zero_budget',
    name: '$0 budget, 1 hour',
    vantage: 'No money, no team, one hour. What is the crudest version that still does the load-bearing thing? What can you delete, hardcode, or fake? Where is the 80/20 cut?',
    tags: ['code', 'general'],
  },
  {
    id: 'infinite_budget',
    name: 'infinite budget, 10 years',
    vantage: 'Infinite compute, infinite engineers, a decade of runway. What is the maximalist version? What would you build if cost and time were not constraints? Then: which piece of that vision is cheap to steal today?',
    tags: ['design', 'wild'],
  },
  {
    id: 'remove_assumption',
    name: 'remove the load-bearing assumption',
    vantage: 'Name the thing everyone treats as fixed — the framework, the database, the request-response model, the network, the user model, the org chart. Imagine it is gone. What becomes possible?',
    tags: ['code', 'design', 'wild'],
  },
  {
    id: 'speedrunner',
    name: 'speedrunner',
    vantage: 'You are a speedrunner. Find glitches, skips, out-of-bounds tricks, frame-perfect shortcuts. What is the abusive-but-legal path that the rules technically allow?',
    tags: ['code', 'wild'],
  },
  {
    id: 'ant_colony',
    name: 'ant colony',
    vantage: 'No central planner. Many dumb agents, local rules, pheromone trails, stigmergy. How does the problem solve itself emergently without coordination?',
    tags: ['code', 'wild'],
  },
  {
    id: 'three_am_oncall',
    name: '3am on-call',
    vantage: 'You are the on-call engineer woken at 3am when this breaks. What design would let you not get paged? What would make diagnosis instant, blast radius minimal, and recovery automatic?',
    tags: ['code', 'design'],
  },
]

// ─── Classification ─────────────────────────────────────────────────────────
// Deterministic: problem kind (drives frame selection), depth (drives frame/idea
// counts), and whether to gather codebase context. Keyword tables live here so
// they are edited in one place and applied consistently — not re-derived by an LLM.
function classify(problemStatement, hasContextFile) {
  const s = problemStatement.toLowerCase()
  const has = (words) => words.some((w) => s.includes(w))

  const CODE_KW = ['function', 'endpoint', 'service', 'schema', 'model', 'query',
    'pattern', 'refactor', 'architecture', 'api', 'data', 'cache', 'queue', 'worker',
    'migration', 'deploy', 'database', 'repository', 'async', 'middleware', 'handler',
    'feature']
  const DESIGN_KW = ['design', 'ux', 'naming', 'product', 'strategy', 'positioning',
    'flow', 'structure', 'interface', 'user experience', 'brand', 'layout']
  const problemKind = has(CODE_KW) ? 'code' : has(DESIGN_KW) ? 'design' : 'general'

  const NAMING_KW = ['name', 'naming', 'variable', 'function name', 'enum', 'label', 'abbreviation']
  const DEEP_KW = ['architecture', 'system design', 'system-design', 'strategy',
    'migration', 'redesign', 'platform']
  let depth
  if (problemStatement.length <= 50 && has(NAMING_KW)) depth = 'quick'
  else if (problemStatement.length > 200 || has(DEEP_KW) || hasContextFile) depth = 'deep'
  else depth = 'default'

  const [frameCount, ideasPerFrame] = { quick: [3, 4], deep: [5, 8], default: [5, 6] }[depth]

  // Ground by default. The only case where codebase context is pointless is a pure
  // naming/label question (depth 'quick'); everything else — features, refactors,
  // test strategy, general design — gets grounded so ideas land in this codebase's
  // reality rather than generic advice. (Fixes feature asks phrased in domain
  // language that keyword-matching alone would misroute and leave ungrounded.)
  const gatherCodeContext = depth !== 'quick'

  return { problemKind, depth, frameCount, ideasPerFrame, gatherCodeContext }
}

// ─── Frame selection ────────────────────────────────────────────────────────
// Picks N frames based on problemKind + a seed-derived offset for variety.
function pickFrames(problemKind, frameCount, seed) {
  // Deterministic offset from a caller-provided seed (epoch seconds, captured in
  // Phase 0). Date.now() is unavailable in workflow scripts — it would break resume.
  const offset = (seed ?? 0) % FRAMES.length

  let eligible
  if (problemKind === 'code') {
    eligible = FRAMES.filter((f) => f.tags.includes('code') || f.tags.includes('design'))
  } else if (problemKind === 'design') {
    eligible = FRAMES.filter((f) => f.tags.includes('design') || f.tags.includes('general'))
  } else {
    eligible = [...FRAMES]
  }

  const wild = eligible.filter((f) => f.tags.includes('wild'))
  const nonWild = eligible.filter((f) => !f.tags.includes('wild'))

  // Rotate selections by offset for variety across runs
  const rotateAndPick = (arr, n) => {
    if (arr.length === 0) return []
    const start = offset % arr.length
    const rotated = [...arr.slice(start), ...arr.slice(0, start)]
    return rotated.slice(0, n)
  }

  // Reserve 1 slot for a wild frame; fill the rest from non-wild (or eligible if not enough)
  const wildPick = rotateAndPick(wild, 1)
  const mainPicks = rotateAndPick(nonWild, frameCount - 1)

  // If not enough non-wild frames, backfill from wild
  const result = [...mainPicks, ...wildPick]
  if (result.length < frameCount) {
    const remaining = eligible.filter((f) => !result.includes(f))
    result.push(...rotateAndPick(remaining, frameCount - result.length))
  }

  return result.slice(0, frameCount)
}

// ─── Schemas ────────────────────────────────────────────────────────────────
const CONTEXT_SCHEMA = {
  type: 'object',
  required: ['relevant_files', 'key_patterns', 'summary'],
  additionalProperties: false,
  properties: {
    relevant_files: {
      type: 'array', items: { type: 'string' },
      description: 'up to 10 file paths most relevant to the problem',
    },
    key_patterns: {
      type: 'array', items: { type: 'string' },
      description: 'up to 5 architectural patterns, conventions, or constraints observed',
    },
    summary: {
      type: 'string',
      description: '2-4 sentence summary of what the codebase currently does in this area',
    },
  },
}

const DIVERGE_SCHEMA = {
  type: 'object',
  required: ['ideas'],
  additionalProperties: false,
  properties: {
    ideas: {
      type: 'array',
      items: {
        type: 'object',
        required: ['text', 'rationale'],
        additionalProperties: false,
        properties: {
          text: { type: 'string', description: 'one phrase or one sentence — the idea itself' },
          rationale: { type: 'string', description: 'why this is worth considering, 1-2 sentences max' },
        },
      },
    },
  },
}

const SCORE_SCHEMA = {
  type: 'object',
  required: ['clusters', 'traps', 'shortlist', 'provocation'],
  additionalProperties: false,
  properties: {
    clusters: {
      type: 'array',
      items: {
        type: 'object',
        required: ['angle', 'ideas'],
        additionalProperties: false,
        properties: {
          angle: { type: 'string', description: 'the structural move this cluster makes, e.g. "cache-shaped plays"' },
          ideas: {
            type: 'array',
            items: {
              type: 'object',
              required: ['text', 'frame', 'novelty', 'viability', 'fit'],
              additionalProperties: false,
              properties: {
                text: { type: 'string' },
                frame: { type: 'string' },
                novelty: { type: 'integer', minimum: 0, maximum: 10 },
                viability: { type: 'integer', minimum: 0, maximum: 10 },
                fit: { type: 'integer', minimum: 0, maximum: 10 },
              },
            },
          },
        },
      },
    },
    traps: {
      type: 'array',
      items: {
        type: 'object',
        required: ['text', 'reason'],
        additionalProperties: false,
        properties: {
          text: { type: 'string', description: 'the idea that is a trap' },
          reason: { type: 'string', description: 'one-line reason it is a trap' },
        },
      },
    },
    shortlist: {
      type: 'array',
      minItems: 3,
      maxItems: 4,
      items: {
        type: 'object',
        required: ['text', 'frame', 'novelty', 'viability', 'fit', 'why_shortlisted', 'is_star'],
        additionalProperties: false,
        properties: {
          text: { type: 'string' },
          frame: { type: 'string' },
          novelty: { type: 'integer', minimum: 0, maximum: 10 },
          viability: { type: 'integer', minimum: 0, maximum: 10 },
          fit: { type: 'integer', minimum: 0, maximum: 10 },
          why_shortlisted: { type: 'string', description: 'why this made the cut' },
          is_star: { type: 'boolean', description: 'true for the non-obvious-but-viable pick' },
        },
      },
    },
    provocation: {
      type: 'string',
      description: 'one wildcard question or reframe that opens a direction nobody explored',
    },
  },
}

const DEEPEN_SCHEMA = {
  type: 'object',
  required: ['sketch', 'load_bearing_risk', 'first_step', 'child_ideas'],
  additionalProperties: false,
  properties: {
    sketch: { type: 'string', description: '4-8 sentences on how the idea would actually work' },
    load_bearing_risk: { type: 'string', description: 'the single biggest risk — what collapses the approach if wrong' },
    first_step: { type: 'string', description: 'first concrete step a builder would take (not "research" — an action)' },
    child_ideas: {
      type: 'array', items: { type: 'string' }, minItems: 3, maxItems: 5,
      description: 'variations, hybrids, combinations, things this unlocks',
    },
  },
}

// ─── Phase: Context ─────────────────────────────────────────────────────────
// Ground by default (classify() gathers for everything except pure naming). When
// the user also supplied a file, MERGE it with the gathered context rather than
// letting the file suppress gathering.
let gathered = null
if (gatherCodeContext) {
  phase('Context')
  gathered = await agent(
    `You are a codebase navigator. The user is brainstorming about this problem:

"${A.problemStatement}"

Find the most relevant code: entry points, existing patterns, constraints, interfaces,
and architectural decisions that relate to this problem. Focus on STRUCTURE and CONSTRAINTS
— what exists, what patterns are established, what would a new approach need to integrate with.

Use the serena symbol tools (find_symbol, get_symbols_overview, find_referencing_symbols)
to navigate efficiently. Do not read entire files — get overviews and key signatures.

Return: relevant_files (max 10 paths that matter most), key_patterns (max 5 architectural
conventions or hard constraints observed), summary (2-4 sentences of what the codebase
currently does in this area and what constraints any solution must respect).

Write every field value as plain prose. Do NOT put XML/HTML tags, markdown code fences, or any
tool-call/result framing (e.g. \`<invoke>\`, \`</summary>\`, \`<result>\`) inside a field — the
tool captures your structured answer; emit only the field content.`,
    { label: 'context', phase: 'Context', schema: CONTEXT_SCHEMA, ...CONTEXT },
  )
}

// Merge gathered context with any user-provided file (either may be absent).
let codeContext = null
if (A.contextFile || gathered) {
  codeContext = {
    relevant_files: [
      ...(A.contextFilePath ? [A.contextFilePath] : []),
      ...(gathered?.relevant_files ?? []),
    ],
    key_patterns: gathered?.key_patterns ?? [],
    summary: [
      A.contextFile ? `Provided file (${A.contextFilePath ?? 'inline'}):\n${A.contextFile.slice(0, 1500)}` : null,
      gathered?.summary ?? null,
    ].filter(Boolean).join('\n\n'),
  }
}

// Human-readable context provenance for the report (computed once, used by every return).
// Reflects what was ACTUALLY obtained, not just intent — a grounding attempt that returned
// nothing is reported as such, so the report never claims grounding that did not happen.
const contextSource = [
  gathered ? 'codebase (auto-gathered)' : gatherCodeContext ? 'codebase (gather returned nothing)' : null,
  A.contextFilePath ? `file: ${A.contextFilePath}` : null,
].filter(Boolean).join(' + ') || 'none'

// ─── Phase: Diverge ─────────────────────────────────────────────────────────
phase('Diverge')

const frames = pickFrames(problemKind, frameCount, A.seed ?? 0)

// Build context block for diverge agents (if available)
const contextBlock = codeContext
  ? `\n\nCODEBASE CONTEXT (ground your ideas in this reality — do not ignore existing constraints):\n${codeContext.summary}${codeContext.key_patterns.length > 0 ? `\nEstablished patterns: ${codeContext.key_patterns.join('; ')}` : ''}${codeContext.relevant_files.length > 0 ? `\nRelevant files: ${codeContext.relevant_files.join(', ')}` : ''}`
  : ''

log(`Diverging: ${frames.length} frames × ${ideasPerFrame} ideas = ${frames.length * ideasPerFrame} target ideas`)

const divergeResults = await parallel(
  frames.map((frame) => () =>
    agent(
      `You are in DIVERGENT mode. You are a generator, not a critic. Do not evaluate.
Do not rank. Do not hedge. Do not apologize. Do not explain trade-offs.

PROBLEM: ${A.problemStatement}
${contextBlock}

YOUR COGNITIVE FRAME: ${frame.name}
${frame.vantage}

Generate ${ideasPerFrame} short distinct ideas under this frame. Each idea is ONE phrase or
ONE sentence — concise, specific, concrete. Not vague directions but actual approaches.

CRITICAL RULE: The first three obvious answers everyone would give are BANNED. You know what
they are — the textbook solutions, the Stack Overflow consensus, the "senior engineer in
thirty seconds" answers. Push PAST them into the awkward middle where the interesting answers
live. If you catch yourself writing something a competent engineer would say without thinking,
delete it and dig deeper.

${codeContext ? 'Your ideas should be grounded in the codebase reality above — propose alternatives TO the existing patterns, not ignorant of them.' : ''}

Write each idea as plain prose. Do NOT include XML/HTML tags, markdown code fences, or any
tool-call/result framing (e.g. \`<invoke>\`, \`</summary>\`, \`<result>\`) in a field — the tool
captures your structured answer; emit only the field content.`,
      { label: frame.id, phase: 'Diverge', schema: DIVERGE_SCHEMA, ...DIVERGE },
    ),
  ),
)

// Collect results, tracking failures
const agentsFailed = []
const allIdeas = []
frames.forEach((frame, i) => {
  if (divergeResults[i] == null) {
    agentsFailed.push(frame.id)
    return
  }
  divergeResults[i].ideas.forEach((idea) => {
    allIdeas.push({ ...idea, frame: frame.name })
  })
})

log(`${allIdeas.length} ideas from ${frames.length - agentsFailed.length} frames`)

if (allIdeas.length === 0) {
  return {
    problemKind,
    frameCount,
    ideasPerFrame,
    frames: frames.map((f) => f.name),
    totalIdeas: 0,
    contextSource,
    clusters: [],
    traps: [],
    shortlist: [],
    deepened: [],
    provocation: 'All diverge agents failed. Try with a more specific problem statement.',
    lowDivergence: false,
    codeContext,
    agentsFailed,
    depth,
  }
}

// ─── Phase: Score & Cluster ─────────────────────────────────────────────────
phase('Score & Cluster')
log(`Scoring ${allIdeas.length} ideas — clustering, trap detection, shortlisting`)

const scored = await agent(
  `You are in CRITIC mode. Your job: score, organize, and surface the best.

PROBLEM: ${A.problemStatement}
${contextBlock}

IDEAS (${allIdeas.length} total from ${frames.length} frames):
${JSON.stringify(allIdeas, null, 1)}

TASKS — execute all five:

1. SCORE each idea on three axes (0-10):
   - novelty: distance from the obvious default (0 = first thing anyone would say; 10 = genuinely surprising angle)
   - viability: could it actually ship given real constraints (0 = physically impossible; 10 = straightforward to implement)
   - fit: does it address the stated problem (0 = solves something else; 10 = bullseye)

2. TRAP DETECTION: flag ideas that look attractive but are traps — hidden cost, false economy,
   won't scale, premature abstraction, solves the wrong problem, yak-shave. One-line reason each.
   Be specific — "too complex" is not a reason; "requires rewriting the auth layer which has 40 consumers" is.

3. CLUSTER: group ALL non-trap ideas into 3-6 clusters by their underlying ANGLE — the
   structural move they make — not by surface keywords or source frame. Label each cluster by
   its angle (e.g. "eliminate-the-middleman plays", "eventual-consistency plays", "push-to-the-edge plays").

4. SHORTLIST: exclude traps, take the 3-4 strongest survivors on the three axes. For each,
   state WHY it made the cut in one sentence. Mark exactly ONE as is_star=true — the
   non-obvious-but-viable pick that a senior engineer would not reach for first but should
   consider seriously. (The weighted ranking — novelty×0.35 + viability×0.40 + fit×0.25 — is
   computed downstream from your integer scores; do not compute or return it yourself.)

5. PROVOCATION: step back from all the ideas. What angle did NO frame explore? What question
   would reframe this problem entirely? One sentence — a direction someone would wish they had
   considered if none of the above ideas land.

Be ruthless. If every idea from a frame is obvious despite the "ban obvious" instruction, score
novelty low. If an idea is creative but impossible given stated constraints, score viability low.
The shortlist must contain ideas that are BOTH non-obvious AND viable — that is the hard part.`,
  { label: 'scorer', phase: 'Score & Cluster', schema: SCORE_SCHEMA, ...SCORER },
)

if (scored == null) {
  agentsFailed.push('scorer')
  return {
    problemKind,
    frameCount,
    ideasPerFrame,
    frames: frames.map((f) => f.name),
    totalIdeas: allIdeas.length,
    contextSource,
    clusters: [],
    traps: [],
    shortlist: [],
    deepened: [],
    provocation: 'Scorer agent failed. Raw ideas were generated but could not be evaluated.',
    lowDivergence: false,
    codeContext,
    agentsFailed,
    depth,
  }
}

// ─── Post-scoring (deterministic) ───────────────────────────────────────────
// Weighted score and low-divergence are arithmetic/threshold facts — computed
// here from the scorer's integers, not delegated to the LLM.
const shortlist = scored.shortlist
  .map((it) => ({
    ...it,
    weighted_score: 0.35 * it.novelty + 0.4 * it.viability + 0.25 * it.fit,
  }))
  .sort((a, b) => b.weighted_score - a.weighted_score)
const lowDivergence = scored.clusters.length <= 2

// ─── Phase: Deepen ──────────────────────────────────────────────────────────
phase('Deepen')
// Always deepen the ★ pick (the tool's headline output), then fill the rest by
// weighted score, up to 3 — so the non-obvious pick can never be crowded out.
const star = shortlist.find((it) => it.is_star)
const topIdeas = [star, ...shortlist.filter((it) => it !== star)]
  .filter(Boolean)
  .slice(0, 3)
log(`Deepening top ${topIdeas.length} ideas`)

const deepenPrompt = (idea) =>
  `You are in FOCUS mode. Take one promising idea and connect dots. Be concrete and specific.

PROBLEM: ${A.problemStatement}
${contextBlock}

IDEA TO DEEPEN: "${idea.text}" (from the "${idea.frame}" frame)
WHY SHORTLISTED: ${idea.why_shortlisted}
WEIGHTED SCORE: ${idea.weighted_score.toFixed(2)} (novelty×0.35 + viability×0.40 + fit×0.25)

TASKS:
1. SKETCH: how would this actually work in 4-8 sentences? Be concrete — name the components,
   the data flow, the interface, the integration points. Not "you could do X" but "X works by Y
   connecting to Z through W."

2. LOAD-BEARING RISK: the single thing that, if wrong, collapses the whole approach. Not a
   generic risk ("might be complex") but a specific falsifiable concern ("if the event bus
   cannot guarantee ordering, the dedup logic fails silently").

3. FIRST STEP: the first concrete action a builder would take. Not "research options" — an
   actual code/design action (create a file, write a test, spike an interface, measure a
   baseline). Something completable in < 2 hours.

4. CHILD IDEAS: 3-5 variations, hybrids with other domains, things this unlocks, or ways to
   de-risk the load-bearing concern. Each is one sentence.

Ground everything in the problem's actual constraints.${codeContext ? ' The codebase context above is real — integrate with it, do not ignore it.' : ''}

Write every field value as plain prose. Do NOT put XML/HTML tags, markdown code fences, or any
tool-call/result framing (e.g. \`<invoke>\`, \`</summary>\`, \`<result>\`) inside a field — the
tool captures your structured answer; emit only the field content.`

const deepened = await parallel(
  topIdeas.map((idea, i) => () =>
    agent(deepenPrompt(idea), { label: `deepen-${i}`, phase: 'Deepen', schema: DEEPEN_SCHEMA, ...DEEPEN }),
  ),
)

// Recover: one hardened repair attempt for any deepen that returned null (schema drift),
// before falling back to the stub — so the top-ranked idea is not lost to a transient failure.
for (let i = 0; i < topIdeas.length; i++) {
  if (deepened[i] != null) continue
  log(`Deepen ${i} produced no valid output — one hardened repair attempt`)
  deepened[i] = await agent(
    deepenPrompt(topIdeas[i]) +
      '\n\nREPAIR: a previous attempt produced no valid output. Keep the sketch to 4-5 plain-prose sentences and emit ONLY the structured field content — absolutely no tags, framing, or code fences.',
    { label: `deepen-${i}-repair`, phase: 'Deepen', schema: DEEPEN_SCHEMA, ...DEEPEN },
  )
}

// Track deepen failures (after the repair pass — only still-null results count as failed)
topIdeas.forEach((_, i) => {
  if (deepened[i] == null) agentsFailed.push(`deepen-${i}`)
})

// ─── Sanitize (deterministic) ───────────────────────────────────────────────
// Strip stray tool-call/result framing an agent occasionally emits inside a free-text
// field value. Matches ONLY these specific literal tags (with an optional namespace prefix
// like `antml:`) — never generic <...> — so code snippets like `expires_at < now`,
// `List[int]`, or `a <= b` survive intact.
const FRAMING_RE = /<\/?(?:[a-z][\w-]*:)?(?:invoke|summary|result|function_calls|parameter)\b[^>]*>/gi
const stripFraming = (s) =>
  typeof s === 'string' ? s.replace(FRAMING_RE, '').replace(/\n{3,}/g, '\n\n').trim() : s
const sanitize = (v) =>
  typeof v === 'string'
    ? stripFraming(v)
    : Array.isArray(v)
      ? v.map(sanitize)
      : v && typeof v === 'object'
        ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, sanitize(x)]))
        : v

// ─── Return ─────────────────────────────────────────────────────────────────
return sanitize({
  problemKind,
  frameCount,
  ideasPerFrame,
  frames: frames.map((f) => f.name),
  totalIdeas: allIdeas.length,
  contextSource,
  clusters: scored.clusters,
  traps: scored.traps,
  shortlist,
  deepened: topIdeas.map((idea, i) => ({
    idea: idea.text,
    frame: idea.frame,
    weighted_score: idea.weighted_score,
    is_star: idea.is_star,
    ...(deepened[i] ?? { sketch: '(agent failed)', load_bearing_risk: 'n/a', first_step: 'n/a', child_ideas: [] }),
  })),
  provocation: scored.provocation,
  lowDivergence,
  codeContext,
  agentsFailed,
  depth,
})
