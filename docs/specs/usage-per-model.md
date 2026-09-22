# Usage per model and per node

Topic: usage-per-model
Revision: 1
Status: Ready
Superseded by: None

## Goal

Report the token usage of a run for each model and for each graph node. Today the `## Usage` footer prints one flat LLM total. Usage events already record `node`, `role` and `model` for each LLM call, but no report groups them. The change adds two groups to the footer. It does not change which calls are metered or how USD is estimated. The footer then has this layout:

```text
llm     14 calls  52100 in  6400 out   $0.1474
        cache  8000 read  1200 write
  by model
    anthropic:claude-sonnet-4-6  4 calls  22000 in  4000 out   $0.1053
        cache  8000 read  1200 write
    anthropic:claude-haiku-4-5  10 calls  30100 in  2400 out   $0.0421
  by node
    research_agent  8 calls  25000 in  1900 out   $0.0345
    ...
exa     6 search  4 highlights        $0.0460
```

## Requirements

### R1 — Print one usage line for each model
- **Status:** active
- **Behavior:** The `## Usage` footer prints a `by model` group. The group has one line for each distinct `model` value of the `llm` events. The key is the raw recorded string, for example `anthropic:claude-haiku-4-5`. Each line shows the calls, the input tokens, the output tokens and the USD. A model that the rate table does not price shows the word `unpriced` in place of the USD.

### R2 — Print one usage line for each graph node
- **Status:** active
- **Behavior:** The `## Usage` footer prints a `by node` group. The group has one line for each distinct `node` value of the `llm` events. The label is the raw node id, for example `research_agent`. Each line shows the calls, the input tokens, the output tokens and the USD of its priced events. When some events of the node are unpriced, the line appends ` + K unpriced`, as the total line does.

### R3 — Keep breakdowns consistent with the totals
- **Status:** active
- **Behavior:** In each group, the line sums equal the `llm` total for the calls, `input_tokens`, `output_tokens`, `cache_read` and `cache_creation`. In each group, the sum of the unrounded priced USD equals the unrounded LLM USD of the total. A line with no cache sub-line counts as zero cache. The printed `.4f` values can differ from the printed total by rounding.

### R4 — Group by the recorded event fields only
- **Status:** active
- **Behavior:** The groups read the fields that the `usage` events already hold. The event schema does not change. An LLM call that fails returns no usage event, so no line counts it. After a resume, the groups show every recorded model id of the thread. No new resume guard is added.

### R5 — Print the groups on every footer path
- **Status:** active
- **Behavior:** The footer prints the groups from the checkpointed `usage` channel. This includes the footer after a clarify interrupt. A run with no `llm` events prints no group. That run still prints the `llm     0 calls` total line and every other current footer line.

### R6 — Keep the contract documents current
- **Status:** active
- **Behavior:** The change updates `docs/spec.md` §7b and the usage paragraph of `docs/architecture.md` in the same change.

### R7 — Test the breakdowns without the network
- **Status:** active
- **Behavior:** Tests build usage events directly or with `tests/fakes.py`. Tests assert the group lines and the sums of R3. No test calls a live vendor.

### R8 — Lay out the groups after the llm total
- **Status:** active
- **Behavior:** The groups print after the `llm` total line and its cache line, and before the `exa` line. `by model` prints first, then `by node`. Each group prints when the run has one or more `llm` events, also when it has only one line. A group starts with a label line indented by two spaces. A row is indented by four spaces and copies the fields of the `llm` total row. A row prints a cache sub-line in the format of the total cache line. It prints it only when its `cache_read` or its `cache_creation` is not zero. The Goal shows the layout.

### R9 — Sort the lines of each group
- **Status:** active
- **Behavior:** Each group sorts its lines by priced USD, highest first. Equal USD sorts by `input_tokens` plus `output_tokens`, highest first. Equal tokens sort by key, in ascending order. A line with no priced USD sorts as USD `0.0`. The order does not depend on the order of the events.

### R10 — Compute each line with the rules of the total
- **Status:** active
- **Behavior:** A line prices each event with `llm_usd` and adds the results. A line counts calls with `int(calls or 1)` for each event, as the total does. An `llm` event with a missing or empty key goes to a line with the key `(unknown)`. An event with no model is unpriced.

### R11 — Keep the public usage functions stable
- **Status:** active
- **Behavior:** `format_usage(events, *, effort=None)` keeps its signature. It returns `[]` when `events` is empty. `aggregate` keeps its current keys. The grouping is a new function. `/plan` names it.

## Out of scope

- A change to which calls emit a usage event, or to vendor retry metering.
- A change to the usage event schema, for example a `topic_id` field.
- A line for each research worker or topic.
- A change to the rate table, the cache multipliers, or the Exa and Elicit prices.
- Groups in the JSONL trace file, in `run_end`, or in the `--verbose` status lines.
- A flag that hides or shows the groups.
- A rounding rule that makes printed line USD values add up to the printed total.
- A model id normalization, and display names for node ids.
- A resume guard for changed model settings.
- A per-model or per-node breakdown of Exa and Elicit tool calls.

## Decisions

### D1 — An agent is a graph node
- **Status:** active
- **Question:** Which unit is an agent in the per-agent breakdown?
- **Answer:** The graph node. `research_agent` gives one line that holds its research and compress calls.
- **Impact:** R2 groups by `node`. No event schema change is necessary.
- **Evidence:** E3

### D2 — The groups print in the footer after the llm total
- **Status:** active
- **Question:** Where in the output do the breakdowns print?
- **Answer:** In `## Usage`, on every run, after the `llm` total line and its cache line and before `exa`.
- **Impact:** R8 placement. The index assertions on the `total` line stay valid.
- **Evidence:** E9

### D3 — Only the footer changes
- **Status:** active
- **Question:** Do the breakdowns also go to the JSONL trace or to the verbose status lines?
- **Answer:** No. Only the `## Usage` footer changes.
- **Impact:** `sink.py`, `status.py` and `run_end` do not change.
- **Evidence:** E24

### D4 — Labelled groups copy the llm row format
- **Status:** active
- **Question:** What layout do the breakdown lines use?
- **Answer:** Indented `by model` and `by node` labels. Rows copy the `llm` total row format, with a separate cache sub-line.
- **Impact:** R8 layout and the exact strings of the tests.
- **Evidence:** E1

### D5 — A node line sums its priced USD and counts unpriced calls
- **Status:** active
- **Question:** What USD does a per-node line show when the node uses more than one model?
- **Answer:** The sum of `llm_usd` over the priced events, plus ` + K unpriced` when some events are unpriced.
- **Impact:** R2 row format and the USD sum rule of R3.
- **Evidence:** E16

### D6 — Each event is priced and then added
- **Status:** active
- **Question:** Does a line price each event, or the summed tokens of the group?
- **Answer:** Each event, then add, the same as the total fold.
- **Impact:** R10. The line USD values add up to the total USD.
- **Evidence:** E20

### D7 — The sum rule applies to unrounded USD
- **Status:** active
- **Question:** Must the printed line USD values add up exactly to the printed total?
- **Answer:** No. The sum rule applies to the unrounded float values.
- **Impact:** R3. Tests compare with a float tolerance.
- **Evidence:** E1

### D8 — Lines sort by USD, then tokens, then key
- **Status:** active
- **Question:** In which order do the lines of each group print?
- **Answer:** Priced USD descending, then input plus output tokens descending, then key ascending.
- **Impact:** R9. The order is deterministic under parallel workers.
- **Evidence:** E15

### D9 — The model key is the raw recorded string
- **Status:** active
- **Question:** Is the model line key the raw recorded id or a normalized one?
- **Answer:** The raw recorded string. Two spellings of one model give two lines.
- **Impact:** R1 key and label.
- **Evidence:** E5

### D10 — A missing key groups as (unknown)
- **Status:** active
- **Question:** How does a breakdown show an `llm` event with a missing or empty `model` or `node`?
- **Answer:** On a line with the key `(unknown)`. A missing model is unpriced.
- **Impact:** R10. The sums of R3 still hold.
- **Evidence:** E21

### D11 — An unpriced model line shows the word unpriced
- **Status:** active
- **Question:** How does an unpriced model line show its USD?
- **Answer:** The word `unpriced` in place of the USD field.
- **Impact:** R1 row format.
- **Evidence:** E18

### D12 — A line counts calls with the total rule
- **Status:** active
- **Question:** How does a breakdown line count calls?
- **Answer:** With `int(calls or 1)` for each event, as the total does.
- **Impact:** R10. The call sums of R3 hold.
- **Evidence:** E17

### D13 — The sum rule covers all four token fields
- **Status:** active
- **Question:** Does the sum rule also cover cache tokens?
- **Answer:** Yes. Input, output, cache read and cache write each add up to the total.
- **Impact:** R3.
- **Evidence:** E19

### D14 — A group prints also with one line
- **Status:** active
- **Question:** Does a group print when it has only one line?
- **Answer:** Yes. Each group prints when the run has one or more `llm` events.
- **Impact:** R8. A default run shows a `by model` line that repeats the total.
- **Evidence:** E5

### D15 — A resume groups recorded models with no guard
- **Status:** active
- **Question:** Does a resume refuse changed model settings?
- **Answer:** No. The groups show every recorded model id. No new resume guard is added.
- **Impact:** R4.
- **Evidence:** E22

### D16 — A run with no llm events keeps its current footer
- **Status:** active
- **Question:** When a run has only tool events, does the `llm     0 calls` total line still print?
- **Answer:** Yes. Only the two groups are left out.
- **Impact:** R5. The tool-only footer tests stay valid.
- **Evidence:** E25

### D17 — The node label is the raw node id
- **Status:** active
- **Question:** Does the `by node` label print the raw node id or a display name?
- **Answer:** The raw node id, for example `research_agent`.
- **Impact:** R2 label. It matches the trace `node` field.
- **Evidence:** E3

### D18 — The public usage functions keep their contracts
- **Status:** active
- **Question:** Do the public contracts of `format_usage` and `aggregate` stay the same?
- **Answer:** Yes. The grouping is a new function that `/plan` names.
- **Impact:** R11.
- **Evidence:** E23

### D19 — An unpriced line sorts as zero USD
- **Status:** active
- **Question:** Where does a line with no priced USD sort?
- **Answer:** It sorts as USD `0.0`, then by tokens and key, with other zero-USD lines.
- **Impact:** R9 order of `unpriced` and `(unknown)` lines.
- **Evidence:** E14

## Repository evidence

- E1: repo:src/exact/usage.py::format_usage
- E2: repo:src/exact/usage.py::aggregate
- E3: repo:src/exact/usage.py::llm_event
- E4: repo:src/exact/config.py#L16
- E5: repo:src/exact/config.py::role_model_id
- E6: repo:src/exact/nodes/research.py#L374
- E7: repo:src/exact/nodes/research.py::_prune
- E8: repo:src/exact/sink.py::_usage_topic
- E9: repo:src/exact/cli.py::_print_report
- E10: repo:docs/spec.md#L254
- E11: repo:docs/spec.md#L390
- E12: repo:tests/test_usage.py
- E13: repo:src/exact/status.py::_research_tool_suffix
- E14: repo:src/exact/usage.py::llm_usd
- E15: repo:src/exact/models.py#L198
- E16: repo:src/exact/usage.py::_fold_llm
- E17: repo:src/exact/usage.py#L281
- E18: repo:src/exact/usage.py#L304
- E19: repo:src/exact/usage.py#L309
- E20: repo:src/exact/usage.py#L206
- E21: repo:docs/spec.md#L260
- E22: repo:src/exact/cli.py::_guard_effort
- E23: repo:tests/test_usage.py#L489
- E24: repo:src/exact/sink.py::_usage_lines
- E25: repo:src/exact/usage.py#L305

## Acceptance criteria

- **R1:** Events for two model ids give two `by model` lines. Each line shows the tokens and USD of its own events only. An unknown model id gives a line that ends with `unpriced`.
- **R2:** Events for two nodes give two `by node` lines. A node with one priced and one unpriced event shows the priced USD and ` + 1 unpriced`.
- **R3:** For a fixed event list, the calls and the four token fields of each group add up to the `llm` total. The unrounded priced USD of each group equals the LLM USD within `pytest.approx`.
- **R4:** Two events with the same model id and different roles give one `by model` line. Events for `research` and `compress` roles from `research_agent` give one `by node` line. A checkpointed thread with events of two model ids, one per invocation, gives two `by model` lines. A node test where the structured call fails adds nothing to any line.
- **R5:** The footer after a clarify interrupt shows the groups of the checkpointed events. A tool-only event list gives the same footer lines as before this change.
- **R6:** `docs/spec.md` §7b and `docs/architecture.md` describe the `by model` and `by node` groups.
- **R7:** `make check` passes with no network access.
- **R8:** The line after the `llm` total line, or after its cache line, is `  by model`. The `by node` group follows the model lines. The `exa` line follows the node lines. A single-model run still prints `  by model` and one line. Each row starts with four spaces. A row with non-zero cache has a cache sub-line. A row with zero cache has none.
- **R9:** Two event lists with the same events in different orders give the same footer. Lines with equal USD and equal tokens sort by key.
- **R10:** An event with `calls=0` counts as one call on its lines. An `llm` event with no `model` shows on a `(unknown)` model line marked `unpriced`. An `llm` event with no `node`, or with an empty `node`, shows on a `(unknown)` node line. An unpriced line and a `$0.0000` line with equal tokens sort by key.
- **R11:** `format_usage([], effort="max")` returns `[]`. The existing `aggregate` key assertions pass unchanged.

## Open questions

None.
