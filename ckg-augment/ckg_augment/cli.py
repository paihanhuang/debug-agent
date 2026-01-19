"""CLI for CKG Augmenter."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .augmenter import CkgAugmenter, load_or_init_ckg, save_ckg
from .fix_db import FixDbDiff, copy_or_init_base_fix_db, upsert_fixes
from .fix_extractor import FixExtractor, filter_metrics_to_source_text
from .report_archive import (
    ArchiveInputs,
    archive_report_and_query,
    parse_combined_report,
    upsert_bundle_index,
)


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
    parser.add_argument("--fix-db", help="Path to base fix DB (optional)")
    parser.add_argument("--fix-db-out", help="Path to output fix DB (optional)")
    parser.add_argument("--fix-db-diff", help="Path to write fix DB diff JSON (optional)")
    parser.add_argument("--no-fix-db", action="store_true", help="Disable fix DB extraction/writing")
    parser.add_argument("--debug-query", help="Path to raw debug-agent query/prompt text file")
    parser.add_argument("--no-archive-reports", action="store_true", help="Disable raw report+query archiving")
    parser.add_argument("--report-library-root", default="output/report_library", help="Archive root (default: output/report_library)")
    parser.add_argument("--run-id", default=None, help="Optional run id (for archive metadata)")
    parser.add_argument("--case-num", type=int, default=None, help="Optional case number (for archive metadata)")
    parser.add_argument("--iter-num", type=int, default=None, help="Optional iteration number (for archive metadata)")

    args = parser.parse_args()

    report_path = Path(args.report)
    ckg_path = Path(args.ckg) if args.ckg else None
    output_path = Path(args.output)
    diff_path = Path(args.diff) if args.diff else None
    feedback_path = Path(args.feedback) if args.feedback else None
    base_fix_db = Path(args.fix_db) if args.fix_db else None
    fix_db_out = Path(args.fix_db_out) if args.fix_db_out else None
    fix_db_diff = Path(args.fix_db_diff) if args.fix_db_diff else None
    debug_query_path = Path(args.debug_query) if args.debug_query else None
    report_library_root = Path(args.report_library_root)

    if not report_path.exists():
        print(f"Error: report not found: {report_path}", file=sys.stderr)
        return 1
    if ckg_path and not ckg_path.exists():
        print(f"Error: CKG not found: {ckg_path}", file=sys.stderr)
        return 1
    if feedback_path and not feedback_path.exists():
        print(f"Error: feedback not found: {feedback_path}", file=sys.stderr)
        return 1
    if base_fix_db and not base_fix_db.exists():
        print(f"Error: base fix DB not found: {base_fix_db}", file=sys.stderr)
        return 1
    if debug_query_path and not debug_query_path.exists():
        print(f"Error: debug query not found: {debug_query_path}", file=sys.stderr)
        return 1
    if not ckg_path and not args.init_empty:
        print("Error: no base CKG provided. Use --ckg or --init-empty.", file=sys.stderr)
        return 1
    if ckg_path and args.init_empty:
        print("Error: provide either --ckg or --init-empty, not both.", file=sys.stderr)
        return 1

    report_text = report_path.read_text(encoding="utf-8")

    # Resolve the exact raw debug-agent query to be archived.
    parsed_human, parsed_query = parse_combined_report(report_text)
    if debug_query_path:
        raw_query = debug_query_path.read_text(encoding="utf-8").strip()
        if not raw_query:
            print(f"Error: debug query file is empty: {debug_query_path}", file=sys.stderr)
            return 1
        query_source = "explicit_file"
        source_query_path = str(debug_query_path)
        # Keep the parsed_debug_query as convenience if report also embeds one
        parsed_debug_query = parsed_query
    else:
        if not parsed_query:
            print(
                "Error: debug query is required but was not provided. "
                "Provide --debug-query, or include an 'E2E Test Query' section in --report.",
                file=sys.stderr,
            )
            return 1
        raw_query = parsed_query
        query_source = "parsed_from_report"
        source_query_path = None
        parsed_debug_query = parsed_query

    # Archive raw report + raw query (default-on). This stores verbatim raw inputs for future reference.
    if not args.no_archive_reports:
        meta = {
            "report_id": report_path.stem,
            "source_report_path": str(report_path),
            "source_query_path": source_query_path,
            "query_source": query_source,
            "run_id": args.run_id,
            "case_num": args.case_num,
            "iter_num": args.iter_num,
            "llm_provider": args.llm_provider,
            "case_filter": args.case,
            "ckg_in_path": str(ckg_path) if ckg_path else None,
            "ckg_out_path": str(output_path),
            "fix_db_in_path": str(base_fix_db) if base_fix_db else None,
            "fix_db_out_path": str(fix_db_out) if fix_db_out else None,
        }
        res = archive_report_and_query(
            library_root=report_library_root,
            inputs=ArchiveInputs(
                report_id=report_path.stem,
                raw_report_text=report_text,
                raw_debug_query_text=raw_query,
                source_report_path=str(report_path),
                source_query_path=source_query_path,
                query_source=query_source,
                parsed_human_report=parsed_human,
                parsed_debug_query=parsed_debug_query,
            ),
            meta=meta,
            no_overwrite=True,
        )
        # Always upsert index (even if bundle existed) so we can link this run/case/iter to the bundle.
        upsert_bundle_index(
            db_path=report_library_root / "report_index.db",
            bundle_id=res.bundle_id,
            report_sha256=res.report_sha256,
            query_sha256=res.query_sha256,
            bundle_path=res.bundle_dir,
            report_id=report_path.stem,
            source_report_path=str(report_path),
            source_query_path=source_query_path,
            query_source=query_source,
            run_id=args.run_id,
            case_num=args.case_num,
            iter_num=args.iter_num,
            ckg_in_path=str(ckg_path) if ckg_path else None,
            ckg_out_path=str(output_path),
            fix_db_in_path=str(base_fix_db) if base_fix_db else None,
            fix_db_out_path=str(fix_db_out) if fix_db_out else None,
        )
        print(f"Archived report+query bundle: {res.bundle_dir} (existed={res.existed})")
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

    # Optional: build/update fix DB (SQLite) compatible with debug-engine FixStore.
    if not args.no_fix_db and fix_db_out:
        try:
            human_report_text = _extract_human_report_only(report_text)
        except Exception:
            human_report_text = report_text

        extractor = FixExtractor(llm_provider=args.llm_provider)
        fixes = extractor.extract_fixes(text=human_report_text, report_id=report_path.stem)
        # Safety filter: keep only metrics that appear in the source text
        fixes = [
            f.__class__(
                case_id=f.case_id,
                root_cause=f.root_cause,
                symptom_summary=f.symptom_summary,
                metrics=filter_metrics_to_source_text(f.metrics, human_report_text),
                fix_description=f.fix_description,
                resolution_notes=f.resolution_notes,
                created_at=f.created_at,
            )
            for f in fixes
        ]

        copy_or_init_base_fix_db(base_db=base_fix_db, out_db=fix_db_out)
        db_diff: FixDbDiff = upsert_fixes(fix_db_out, fixes)
        print(f"Fix DB saved to: {fix_db_out}")
        if fix_db_diff:
            fix_db_diff.parent.mkdir(parents=True, exist_ok=True)
            fix_db_diff.write_text(json.dumps(db_diff.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Fix DB diff saved to: {fix_db_diff}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _extract_human_report_only(raw: str) -> str:
    """If raw is a combined data/<case> file, return only the human report portion."""
    lines = (raw or "").splitlines()
    marker = None
    for i, l in enumerate(lines):
        if "E2E Test Query" in l:
            marker = i
            break
    if marker is None:
        return raw.strip()

    report_end = marker
    for j in range(marker - 1, -1, -1):
        if lines[j].strip() == "---":
            report_end = j
            break
    return "\n".join(lines[:report_end]).strip()
