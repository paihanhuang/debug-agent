# Judge Module - Unit Test Results

Test Date: 2026-01-14T23:39:49

## Test Results

```
✓ Test 1: Weights sum to 1.0
✓ Test 2: Root cause accuracy weight is 50%
✓ Test 3: Composite score calculation = 4.35 (old scale)
✓ Test 4: Grade B for 4.35 (old scale)
✓ Test 5: Grade A for 4.5 (old scale)

All unit tests passed!
```

## Weights Verification

| Dimension | Weight | Status |
|-----------|:------:|:------:|
| Root Cause Accuracy | 50% | ✓ |
| Causal Chain Completeness | 20% | ✓ |
| Metric Precision | 15% | ✓ |
| Reasoning Quality | 10% | ✓ |
| Actionability | 5% | ✓ |
| **Total** | **100%** | ✓ |

## Grade Thresholds (1-10 scale)

| Score Range | Grade | Status |
|-------------|:-----:|:------:|
| >= 9.0 | A+ | ✓ |
| >= 8.0 | A | ✓ |
| >= 7.0 | B | ✓ |
| >= 6.0 | C | ✓ |
| >= 5.0 | D | ✓ |
| < 5.0 | F | ✓ |

## Test Command

```bash
source .venv/bin/activate
python -c "from judge.models import DimensionScore, EvaluationResult, DEFAULT_WEIGHTS; ..."
```
