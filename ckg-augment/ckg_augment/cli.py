"""CLI for CKG Augmenter."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .augmenter import CkgAugmenter, load_ckg, save_ckg


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ckg-augment",
        description="Augment an existing CKG with a new expert report.",
    )
    parser.add_argument("--report", required=True, help="Path to expert report text file")
    parser.add_argument("--ckg", required=True, help="Path to base CKG JSON")
    parser.add_argument("--output", required=True, help="Path to output augmented CKG JSON")
    parser.add_argument("--diff", help="Path to write augmentation diff JSON")
    parser.add_argument("--llm-provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--no-fuzzy", action="store_true", help="Disable fuzzy entity matching")
    parser.add_argument("--similarity-threshold", type=float, default=0.88)

    args = parser.parse_args()

    report_path = Path(args.report)
    ckg_path = Path(args.ckg)
    output_path = Path(args.output)
    diff_path = Path(args.diff) if args.diff else None

    if not report_path.exists():
        print(f"Error: report not found: {report_path}", file=sys.stderr)
        return 1
    if not ckg_path.exists():
        print(f"Error: CKG not found: {ckg_path}", file=sys.stderr)
        return 1

    report_text = report_path.read_text(encoding="utf-8")
    base_ckg = load_ckg(ckg_path)

    augmenter = CkgAugmenter(
        llm_provider=args.llm_provider,
        fuzzy_match=not args.no_fuzzy,
        similarity_threshold=args.similarity_threshold,
    )

    augmented_ckg, diff = augmenter.augment(
        report_text=report_text,
        base_ckg=base_ckg,
        report_id=report_path.stem,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_ckg(augmented_ckg, output_path)
    print(f"Augmented CKG saved to: {output_path}")

    if diff_path:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(json.dumps(diff.to_dict(), indent=2), encoding="utf-8")
        print(f"Diff saved to: {diff_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
