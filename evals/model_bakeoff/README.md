# Hermes Agency Model Bake-off

This harness is for comparing model sets against Hermes-realistic work instead of choosing models by vibes.

Run each task with the same profile and capture the result in `results/*.jsonl` using the schema in `result.schema.json`.

Suggested scoring dimensions, each 1-5 unless noted otherwise:

- correctness
- instruction_following
- code_quality
- safety
- test_quality
- cleanup_burden, where lower is better
- latency
- estimated_cost
- human_preference

Bake-off results should be used to revise packaged presets. Provider marketing claims should not be treated as final.
