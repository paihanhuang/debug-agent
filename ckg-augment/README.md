# CKG Augmenter

Augments an existing CKG JSON with new knowledge extracted from a human expert
report.

## Usage

```bash
python -m ckg_augment.cli \
  --report data/first \
  --ckg output/full_ckg.json \
  --output output/augmented_ckg.json \
  --diff output/augmentation_diff.json
```

## Options
- `--llm-provider`: `openai` (default) or `anthropic`
- `--no-fuzzy`: disable fuzzy entity matching
- `--similarity-threshold`: fuzzy match threshold (default: 0.88)
