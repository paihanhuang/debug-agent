"""CLI for CKG Augmenter."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .augmenter import CkgAugmenter, load_or_init_ckg, save_ckg


def main() -> int:
    # Best-effort load of `.env` so users can store OPENAI_API_KEY there.
    # This keeps `ckg-augment` consistent with other parts of the repo.
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        prog="ckg-augment",
        description="Augment an existing CKG with a new expert report.",
    )
    parser.add_argument("--report", required=True, help="Path to expert report text file")
    parser.add_argument("--ckg", help="Path to base CKG JSON")
    parser.add_argument("--init-empty", action="store_true", help="Initialize from empty CKG (no --ckg)")
    parser.add_argument("--output", required=True, help="Path to output augmented CKG JSON")
    parser.add_argument("--diff", help="Path to write augmentation diff JSON")
    parser.add_argument("--feedback", help="Path to closed-loop feedback JSON (optional)")
    parser.add_argument("--case", default="all", choices=["all", "case1", "case2", "case3"])
    parser.add_argument("--llm-provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--no-fuzzy", action="store_true", help="Disable fuzzy entity matching")
    parser.add_argument("--similarity-threshold", type=float, default=0.88)

    args = parser.parse_args()

    report_path = Path(args.report)
    ckg_path = Path(args.ckg) if args.ckg else None
    output_path = Path(args.output)
    diff_path = Path(args.diff) if args.diff else None
    feedback_path = Path(args.feedback) if args.feedback else None

    if not report_path.exists():
        print(f"Error: report not found: {report_path}", file=sys.stderr)
        return 1
    if ckg_path and not ckg_path.exists():
        print(f"Error: CKG not found: {ckg_path}", file=sys.stderr)
        return 1
    if feedback_path and not feedback_path.exists():
        print(f"Error: feedback not found: {feedback_path}", file=sys.stderr)
        return 1
    if not ckg_path and not args.init_empty:
        print("Error: no base CKG provided. Use --ckg or --init-empty.", file=sys.stderr)
        return 1
    if ckg_path and args.init_empty:
        print("Error: provide either --ckg or --init-empty, not both.", file=sys.stderr)
        return 1

    report_text = report_path.read_text(encoding="utf-8")
    base_ckg = load_or_init_ckg(ckg_path, init_empty=bool(args.init_empty))
    feedback = json.loads(feedback_path.read_text(encoding="utf-8")) if feedback_path else None

    augmenter = CkgAugmenter(
        llm_provider=args.llm_provider,
        fuzzy_match=not args.no_fuzzy,
        similarity_threshold=args.similarity_threshold,
    )

    augmented_ckg, diff = augmenter.augment(
        report_text=report_text,
        base_ckg=base_ckg,
        report_id=report_path.stem,
        feedback=feedback,
        case_filter=args.case,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_ckg(augmented_ckg, output_path)
    print(f"Augmented CKG saved to: {output_path}")

    if diff_path:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(json.dumps(diff.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Diff saved to: {diff_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
