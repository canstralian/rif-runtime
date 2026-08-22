# code_refinement_mst

This evaluation measures how long an agent preserves functional correctness while RIF governs repeated refinement instructions against a solution.

The evaluation treats refinement as a governed loop rather than a one-shot generation task:

```text
generation
  -> RIF policy evaluation
  -> candidate verification
  -> regression classification
  -> recorded governance result
  -> next turn / stop
```

## Metric: MST-RIF

**Mean Sustainable Turns before the first verified regression.**

Higher MST-RIF means the evaluated agent preserved the task's tested behaviour for more refinement turns before the first verified regression.

Any numeric result in generated reports is an experiment result, not a project-wide model-quality claim. Do not copy sample results into release or marketing documentation without identifying the exact task set, model, harness version, and run.

## Layout

```text
schema/             task / session / result JSON Schemas
tasks/python/        task definitions
runners/             session orchestration, sandbox execution, scoring
sessions/generated/  generated traces (gitignored)
reports/              generated reports (gitignored)
```

## Circuit

```text
task
  -> agent generates/refines candidate
  -> RIFRuntime evaluates refinement request
  -> sandbox runner verifies candidate
  -> regression becomes a recorded governance result
  -> score_session()
```

The harness does not embed a specific model client. Generation is supplied through a `CodeAgent` implementation.

## Running a session

```bash
python rif-evals/code_refinement_mst/runners/run_session.py \
  rif-evals/code_refinement_mst/tasks/python/task_001_palindrome.json \
  --agent your_module:YourCodeAgent
```

For harness-only testing, `ScriptedAgent` is used by the repository's tests to exercise deterministic sequences without a live model.

## Required policy

The harness gates every refinement turn through `RIFRuntime.evaluate()` with
`action="code.refine"`. The default policy denies by default, so the runtime you
hand the harness must carry a rule permitting that action, or every turn is
returned as `blocked`:

```json
{
  "id": "allow_eval_code_refine",
  "effect": "allow",
  "action": "code.refine",
  "target": "*",
  "reason": "MST eval harness refinement turns"
}
```

A blocked turn records `tests_passed: null`, and `score_session()` treats a null
as "not a regression". A fully blocked session therefore scores a *perfect* MST
while verifying nothing. Check `verification_status` in the trace before
reading any score.

## Constraint alignment

If constrained decoding is introduced, evaluate the constrainer as part of the experiment rather than assuming that stronger syntactic constraints improve functional correctness.

A constraint configuration should declare its intended surface, completeness, soundness, and distortion risk. The evaluation should compare constrained and unconstrained baselines under the same task/run conditions.

## Adding tasks

A task is a JSON definition validated against `schema/task.schema.json`. Keep tasks self-contained and deterministic where possible. The first milestone for a new task set is a reproducible harness result, not a leaderboard claim.
