from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.llm.client import BaseLLMClient, LLMClient

from .fix_db import FixRecord, stable_fix_case_id


FIX_EXTRACTION_SYSTEM_PROMPT = """You extract HISTORICAL FIX suggestions from a human expert debugging report.

Rules:
- Base fixes strictly on the report's identified root cause(s) and reasoning.
- Even if the report doesn't explicitly list a "fix", you SHOULD propose 1-3 practical, conservative next-actions
  that are clearly implied by the report (e.g., verify CM voting / SW_REQ2, check PowerHal voting / SW_REQ3,
  adjust control policy/strategy, confirm MMDVFS OPP behavior).
- Do not invent new root causes. Do not fabricate numeric metrics.
- Keep fixes short and practical (1-3 sentences).
- Metrics: include only metrics explicitly present in the text (e.g., DDR5460 %, DDR6370 %, CPU freqs, VCORE levels).

Return ONLY valid JSON."""


FIX_EXTRACTION_PROMPT = """Extract historical fixes from the following human expert report text.

Text:
{text}

Return JSON in this structure:
{{
  "fixes": [
    {{
      "root_cause": "CM|PowerHal|MMDVFS|... (short label)",
      "symptom_summary": "when to apply (short)",
      "metrics": {{"key": "value"}},
      "fix_description": "actionable recommendation",
      "resolution_notes": "optional extra notes"
    }}
  ]
}}"""


@dataclass
class FixExtractor:
    llm_provider: str = "openai"
    llm_client: BaseLLMClient | None = None

    def __post_init__(self) -> None:
        self._llm = self.llm_client or LLMClient.create(provider=self.llm_provider)

    def extract_fixes(self, *, text: str, report_id: str) -> list[FixRecord]:
        prompt = FIX_EXTRACTION_PROMPT.format(text=text)
        try:
            obj = self._llm.complete_json(prompt, FIX_EXTRACTION_SYSTEM_PROMPT)
        except Exception:
            return []

        fixes: list[FixRecord] = []
        for item in obj.get("fixes", []) or []:
            raw_rc = item.get("root_cause", "")
            fix_desc = str(item.get("fix_description", "")).strip()
            if not fix_desc:
                continue
            symptom = str(item.get("symptom_summary", "")).strip()
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            notes = str(item.get("resolution_notes", "")).strip()

            rcs = _split_root_causes(raw_rc)
            for root_cause in rcs:
                if not root_cause:
                    continue
                case_id = stable_fix_case_id(report_id=report_id, root_cause=root_cause, fix_description=fix_desc)
                fixes.append(
                    FixRecord(
                        case_id=case_id,
                        root_cause=root_cause,
                        symptom_summary=symptom,
                        metrics=metrics or {},
                        fix_description=fix_desc,
                        resolution_notes=notes,
                    )
                )
        return fixes


_NUM_TOKEN = re.compile(r"[-+]?(?:\\d+\\.\\d+|\\d+)")


def filter_metrics_to_source_text(metrics: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Safety: keep only metrics whose key OR numeric value appears in the source text."""
    if not metrics:
        return {}
    src = source_text or ""
    out: dict[str, Any] = {}
    for k, v in metrics.items():
        ks = str(k)
        vs = "" if v is None else str(v)
        keep = False
        if ks and ks in src:
            keep = True
        if not keep:
            nums = _NUM_TOKEN.findall(vs)
            if any(n in src for n in nums):
                keep = True
        if keep:
            out[k] = v
    return out


def _split_root_causes(raw: Any) -> list[str]:
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw]
    else:
        s = str(raw or "").strip()
        if not s:
            return []
        # common separators in our reports
        for sep in ["、", "/", ",", ";", " and ", " & "]:
            s = s.replace(sep, "|")
        parts = [p.strip() for p in s.split("|")]

    norm: list[str] = []
    for p in parts:
        if not p:
            continue
        low = p.lower()
        if low in {"cpu manager", "cm"}:
            norm.append("CM")
            continue
        if low in {"powerhal", "power hal"}:
            norm.append("PowerHal")
            continue
        if low in {"mmdvfs"}:
            norm.append("MMDVFS")
            continue
        norm.append(p)
    # stable de-dup
    out: list[str] = []
    seen = set()
    for x in norm:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

