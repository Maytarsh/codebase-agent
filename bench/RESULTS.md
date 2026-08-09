# Measurement

Ten questions about this repository (~1,500 lines, 8 modules), scored on whether
the agent cited the file a correct answer needs. Model: `claude-opus-5`. Three
runs, one variable moved at a time, $3.14 in total.

| condition | correct | turns | cost |
|---|---|---|---|
| `good` descriptions, full system prompt | 10/10 | 41 | $1.0875 |
| `vague` descriptions, full system prompt | 10/10 | 39 | $1.0175 |
| `vague` descriptions, terse system prompt | 10/10 | 39 | $1.0353 |

Turns per question:

| id | good | vague | terse | spread |
|---|---|---|---|---|
| toolerror | 3 | 3 | 3 | – |
| confinement | 5 | 6 | 6 | 1 |
| unknown-tool | 6 | 5 | 4 | 2 |
| search-cap | 4 | 4 | 5 | 1 |
| parallel | 4 | 4 | 4 | – |
| sdk-seam | 3 | 3 | 3 | – |
| replay-check | 5 | 3 | 3 | 2 |
| pricing | 3 | 3 | 3 | – |
| answer-shape | 3 | 3 | 3 | – |
| root-absent | 5 | 5 | 5 | – |

## The finding

**Tool description wording had no measurable effect on this task.** Degrading
the descriptions from prescriptive ("call `search` before `read_file` when you
do not already know which file to open") to descriptive ("searches the
repository for a regular expression") left the score at 10/10 and moved the turn
count by two. Removing the duplicate instruction from the system prompt as well
changed nothing further.

The result is a null, and the reason it is a *credible* null rather than an
uninformative one is the last column. The total spread across all three
conditions is two turns — the same as the spread on `unknown-tool` alone. The
between-condition difference is no larger than the jitter on a single question,
so no separate variance estimate is needed to say it is not signal. Six of ten
questions were identical in all three runs. The control was also the most
expensive of the three, which is the wrong direction for the hypothesis.

## Why nothing moved

Three reasons, in descending order of how much I think they matter.

**The benchmark saturates.** 10/10 in the control leaves nowhere to fall. With
eight modules, `list_files` returns the entire repository in one call and any
strategy converges in three to six turns. Tool descriptions are guidance for
choosing under ambiguity, and on a repository this size there is no ambiguity to
resolve.

**The tool names carry the information.** `search`, `read_file` and `list_files`
are not cryptic. A capable model infers "search before you read" from the names
and the schemas alone; the description was telling it something it had already
worked out. The prescriptive wording is not wrong, it is redundant — and this
run measured its redundancy, not its value.

**Turn count is a coarse instrument.** It ranges 3–6 across the whole question
set, so a real effect has to be worth a full turn before it becomes visible.
Token counts are continuous and would resolve smaller differences; scoring on
prompt tokens rather than turns is the change I would make first.

## What I got wrong

The first pair of runs was not the experiment I claimed. The system prompt says
"search before you read: searching is far cheaper than opening files one at a
time" — the same instruction I was removing from the tool descriptions. So the
first `vague` run had deleted one of two copies of the guidance rather than the
guidance, and the null it produced supported a much narrower claim than the one
I set out to test. The `--system terse` flag exists because of that, and the
third run is the one the first two should have been.

Cost of the mistake: one wasted run, about a dollar. Cost of not noticing it:
a finding that would not have survived a follow-up question.

## What I would change

- **Break the ceiling.** Point the agent at a repository large enough that a bad
  search strategy costs real turns, or ask questions whose answers span several
  files. A control that scores 10/10 cannot measure degradation.
- **Score on tokens, not turns.** Continuous beats discrete at this sample size.
- **Widen the tool surface.** Three well-named tools make selection easy. The
  regime where descriptions matter is more tools, overlapping purposes, or names
  that do not announce themselves.
- **Run each condition twice.** Not needed to defend this null, but required the
  moment any positive difference is claimed.

The transferable point is about scope. "Tool descriptions move the number" is a
claim about a regime — weaker models, more tools, larger search spaces — and
this project is not in it. Measuring is how you find that out; assuming it and
shipping the prescriptive wording as a best practice is how you would not.
