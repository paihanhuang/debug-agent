"""CKG Augmenter: merge new report knowledge into an existing CKG."""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.extraction.entity_extractor import EntityExtractor
from src.extraction.relation_extractor import RelationExtractor
from src.graph.models import CausalGraph, Entity, EntityType, Relation, RelationType


@dataclass
class AugmentDiff:
    added_entities: list[str]
    updated_entities: list[str]
    added_relations: list[dict[str, str]]
    updated_relations: list[dict[str, str]]
    skipped_relations: list[dict[str, str]]
    conflicts: list[str]
    feedback_added_entities: list[str] | None = None
    feedback_skipped_existing: list[str] | None = None
    feedback_added_relations: list[dict[str, str]] | None = None
    feedback_skipped_existing_relations: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_entities": self.added_entities,
            "updated_entities": self.updated_entities,
            "added_relations": self.added_relations,
            "updated_relations": self.updated_relations,
            "skipped_relations": self.skipped_relations,
            "conflicts": self.conflicts,
            "feedback_added_entities": self.feedback_added_entities or [],
            "feedback_skipped_existing": self.feedback_skipped_existing or [],
            "feedback_added_relations": self.feedback_added_relations or [],
            "feedback_skipped_existing_relations": self.feedback_skipped_existing_relations or [],
        }


class CkgAugmenter:
    """Augment a base CKG with knowledge from a new expert report."""

    def __init__(
        self,
        llm_provider: str = "openai",
        entity_extractor: EntityExtractor | None = None,
        relation_extractor: RelationExtractor | None = None,
        fuzzy_match: bool = True,
        similarity_threshold: float = 0.88,
    ):
        self._entity_extractor = entity_extractor or EntityExtractor(llm_provider=llm_provider)
        self._relation_extractor = relation_extractor or RelationExtractor(llm_provider=llm_provider)
        self._fuzzy_match = fuzzy_match
        self._similarity_threshold = similarity_threshold

    def augment(
        self,
        report_text: str,
        base_ckg: CausalGraph,
        report_id: str,
        feedback: dict[str, Any] | None = None,
        case_filter: str = "all",
    ) -> tuple[CausalGraph, AugmentDiff]:
        """Augment base CKG with report-derived knowledge."""
        diff = AugmentDiff(
            added_entities=[],
            updated_entities=[],
            added_relations=[],
            updated_relations=[],
            skipped_relations=[],
            conflicts=[],
            feedback_added_entities=[],
            feedback_skipped_existing=[],
            feedback_added_relations=[],
            feedback_skipped_existing_relations=[],
        )

        extracted_entities = self._entity_extractor.extract_entities(report_text)
        extracted_relations = self._relation_extractor.extract_relations(
            report_text, extracted_entities
        )

        existing_entities = list(base_ckg.get_entities())
        entity_index = self._build_entity_index(existing_entities)

        id_map: dict[str, str] = {}
        for entity in extracted_entities:
            # Normalize metric labels to avoid overfitting to specific numeric values.
            # This improves cross-case reuse/matching (e.g., "VCORE usage 82.6%" vs "VCORE usage 29.32%").
            if entity.entity_type == EntityType.METRIC:
                canon_label, metric_attrs = self._canonicalize_metric_label(entity.label)
                if canon_label:
                    entity.label = canon_label
                # Store extracted metric values on the extracted entity so they can be carried into base CKG.
                # (EntityExtractor usually doesn't populate attributes for entities.)
                if metric_attrs:
                    entity.attributes = {**(entity.attributes or {}), **metric_attrs}

            matched_id = self._match_entity(entity, entity_index, existing_entities)
            if matched_id:
                id_map[entity.id] = matched_id
                self._merge_entity(base_ckg, matched_id, entity, report_id, diff)
            else:
                new_id = self._generate_entity_id(entity, report_id)
                id_map[entity.id] = new_id
                # Carry metric normalization attrs (raw label + extracted values) into stored entity attributes.
                extra_attrs: dict[str, Any] = {}
                if entity.entity_type == EntityType.METRIC and (entity.attributes or {}):
                    for k in ("raw_label", "metric_values"):
                        if k in entity.attributes:
                            extra_attrs[k] = entity.attributes[k]
                new_entity = Entity(
                    id=new_id,
                    entity_type=entity.entity_type,
                    label=entity.label,
                    description=entity.description,
                    attributes={**self._build_provenance(report_id, entity.source_text), **extra_attrs},
                    confidence=entity.confidence,
                    source_text=entity.source_text,
                )
                base_ckg.add_entity(new_entity)
                diff.added_entities.append(new_id)
                self._index_entity(entity_index, new_entity)

        existing_relation_keys = self._relation_keys(base_ckg.get_relations())
        for relation in extracted_relations:
            source_id = id_map.get(relation.source_id)
            target_id = id_map.get(relation.target_id)
            if not source_id or not target_id:
                diff.skipped_relations.append(
                    {"source": relation.source_id, "target": relation.target_id, "type": relation.relation_type.value}
                )
                continue

            key = (source_id, relation.relation_type.value, target_id)
            if key in existing_relation_keys:
                self._merge_relation(base_ckg, key, relation, report_id, diff)
                continue

            new_relation = Relation(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                evidence=relation.evidence,
                causal_effect=relation.causal_effect,
                attributes=self._build_provenance(report_id, relation.evidence),
            )
            try:
                base_ckg.add_relation(new_relation)
                existing_relation_keys.add(key)
                diff.added_relations.append(
                    {"source": source_id, "target": target_id, "type": relation.relation_type.value}
                )
            except Exception as exc:
                diff.conflicts.append(str(exc))

        # Phase B: apply orchestrator feedback (add-only, deterministic)
        if feedback:
            missing = extract_missing_elements(feedback, case_filter=case_filter)
            missing_norm = [self._normalize_feedback_missing_element(m) for m in missing]
            missing_norm = [m for m in missing_norm if m]
            # stable de-dup while preserving order
            seen = set()
            missing_norm_dedup = []
            for m in missing_norm:
                if m in seen:
                    continue
                seen.add(m)
                missing_norm_dedup.append(m)

            self._ensure_missing_entities(base_ckg, missing_norm_dedup, report_id=report_id, diff=diff)
            self._ensure_missing_relations(base_ckg, missing_norm_dedup, report_id=report_id, diff=diff)

        # Phase C: deterministic autolink pass to reduce isolated metric/component nodes.
        # This adds ONLY non-causal, low-confidence evidential edges (Metric -> Component via INDICATES).
        self._autolink_metrics_to_components(base_ckg, report_id=report_id, diff=diff)

        return base_ckg, diff

    @staticmethod
    def _normalize_feedback_missing_element(s: str) -> str:
        """Normalize missing elements to stable CKG labels (v1)."""
        s = (s or "").strip()
        if not s:
            return ""
        low = s.lower()
        if "拉檔" in s:
            return "拉檔"
        if "frequency throttling" in low:
            return "拉檔"
        return s

    def _ensure_missing_relations(
        self,
        graph: CausalGraph,
        missing_labels: list[str],
        report_id: str,
        diff: AugmentDiff,
    ) -> None:
        """Add safe, non-causal relations implied by missing elements.

        This is intentionally conservative:
        - never adds CAUSES
        - adds only evidential/analysis-flow relations with low confidence
        - all relations are provenance-tagged
        """
        if not missing_labels:
            return

        if diff.feedback_added_relations is None:
            diff.feedback_added_relations = []
        if diff.feedback_skipped_existing_relations is None:
            diff.feedback_skipped_existing_relations = []

        existing_relation_keys = self._relation_keys(graph.get_relations())

        # Build label indices for resolution.
        entities = list(graph.get_entities())
        by_norm = {self._normalize_label(e.label): e.id for e in entities}
        # For contains matching (CM often appears as "CM causing ...")
        def _find_best_id_contains(token: str, prefer_type: EntityType | None = None) -> str | None:
            t = token.strip().lower()
            if not t:
                return None
            # exact normalized match first
            exact = by_norm.get(self._normalize_label(token))
            if exact:
                return exact
            # type-preferred contains match
            candidates = []
            for e in entities:
                if prefer_type and e.entity_type != prefer_type:
                    continue
                if t in (e.label or "").lower():
                    candidates.append(e)
            if candidates:
                return candidates[0].id
            # fallback contains match without type constraint
            for e in entities:
                if t in (e.label or "").lower():
                    return e.id
            return None

        def _ensure_component(label: str) -> str:
            norm = self._normalize_label(label)
            if norm in by_norm:
                return by_norm[norm]
            eid = generate_feedback_entity_id(EntityType.COMPONENT, label)
            if graph.get_entity(eid) is not None:
                eid = generate_feedback_entity_id(EntityType.COMPONENT, f"{label}:{report_id}")
            graph.add_entity(
                Entity(
                    id=eid,
                    entity_type=EntityType.COMPONENT,
                    label=label,
                    description="",
                    attributes={"provenance": [{"source": "closed_loop_feedback", "report_id": report_id, "reason": "missing_relation_target"}]},
                    confidence=1.0,
                    source_text="",
                )
            )
            by_norm[norm] = eid
            entities.append(graph.get_entity(eid))  # type: ignore[arg-type]
            return eid

        def _ensure_observation(label: str) -> str:
            norm = self._normalize_label(label)
            if norm in by_norm:
                return by_norm[norm]
            eid = generate_feedback_entity_id(EntityType.OBSERVATION, label)
            if graph.get_entity(eid) is not None:
                eid = generate_feedback_entity_id(EntityType.OBSERVATION, f"{label}:{report_id}")
            graph.add_entity(
                Entity(
                    id=eid,
                    entity_type=EntityType.OBSERVATION,
                    label=label,
                    description="",
                    attributes={"provenance": [{"source": "closed_loop_feedback", "report_id": report_id, "reason": "missing_relation_source"}]},
                    confidence=1.0,
                    source_text="",
                )
            )
            by_norm[norm] = eid
            entities.append(graph.get_entity(eid))  # type: ignore[arg-type]
            return eid

        def _ensure_metric(label: str) -> str:
            canon_label, metric_attrs = self._canonicalize_metric_label(label)
            norm = self._normalize_label(canon_label)
            if norm in by_norm:
                return by_norm[norm]
            eid = generate_feedback_entity_id(EntityType.METRIC, canon_label)
            if graph.get_entity(eid) is not None:
                eid = generate_feedback_entity_id(EntityType.METRIC, f"{canon_label}:{report_id}")
            graph.add_entity(
                Entity(
                    id=eid,
                    entity_type=EntityType.METRIC,
                    label=canon_label,
                    description="",
                    attributes={
                        "provenance": [{"source": "closed_loop_feedback", "report_id": report_id, "reason": "missing_metric"}],
                        **(metric_attrs or {}),
                    },
                    confidence=1.0,
                    source_text="",
                )
            )
            by_norm[norm] = eid
            entities.append(graph.get_entity(eid))  # type: ignore[arg-type]
            return eid

        def _add_relation(source_id: str, rel_type: RelationType, target_id: str, rule_id: str) -> None:
            key = (source_id, rel_type.value, target_id)
            if key in existing_relation_keys:
                diff.feedback_skipped_existing_relations.append(
                    {"source": source_id, "target": target_id, "type": rel_type.value}
                )
                return
            rel = Relation(
                source_id=source_id,
                target_id=target_id,
                relation_type=rel_type,
                confidence=0.3,
                evidence=f"closed_loop_feedback_relation:{rule_id}",
                causal_effect=None,
                attributes={
                    "provenance": [
                        {
                            "source": "closed_loop_feedback_relation",
                            "report_id": report_id,
                            "reason": "missing_elements",
                            "rule_id": rule_id,
                        }
                    ]
                },
            )
            graph.add_relation(rel, validate_dag=False)
            existing_relation_keys.add(key)
            diff.feedback_added_relations.append({"source": source_id, "target": target_id, "type": rel_type.value})

        # Resolve key targets
        cm_target = _find_best_id_contains("CM", prefer_type=EntityType.ROOT_CAUSE) or _find_best_id_contains(
            "CM"
        ) or _ensure_component("CM")
        powerhal_target = _find_best_id_contains("PowerHal", prefer_type=EntityType.COMPONENT) or _ensure_component(
            "PowerHal"
        )
        ddr_target = _find_best_id_contains("DDR", prefer_type=EntityType.COMPONENT) or None
        cpu_target = _find_best_id_contains("CPU", prefer_type=EntityType.COMPONENT) or None

        # Rule A/B/C/D dispatch
        for m in missing_labels:
            low = m.lower()

            # Rule A: SW_REQ mapping
            if m.strip().upper() == "SW_REQ2":
                sw = _ensure_observation("SW_REQ2")
                _add_relation(sw, RelationType.INDICATES, cm_target, rule_id="sw_req2_indicates_cm")
                continue
            if m.strip().upper() == "SW_REQ3":
                sw = _ensure_observation("SW_REQ3")
                _add_relation(sw, RelationType.INDICATES, powerhal_target, rule_id="sw_req3_indicates_powerhal")
                continue

            # Rule B: 拉檔
            if "拉檔" in m or "frequency throttling" in low:
                th = _ensure_observation("拉檔")
                _add_relation(th, RelationType.INDICATES, cm_target, rule_id="throttling_indicates_cm")
                continue

            # Rule C: specific metrics
            if "ddr5460" in low or "ddr6370" in low:
                met = _ensure_metric(m)
                if ddr_target is None:
                    ddr_target = _ensure_component("DDR")
                _add_relation(met, RelationType.INDICATES, ddr_target, rule_id="ddr_metric_indicates_ddr")
                continue
            if m.strip().lower() == "cpu frequencies":
                met = _ensure_metric("CPU frequencies")
                if cpu_target is None:
                    cpu_target = _ensure_component("CPU")
                _add_relation(met, RelationType.INDICATES, cpu_target, rule_id="cpu_freq_indicates_cpu")
                continue

            # Rule D: chain parsing
            if "->" in m or "→" in m:
                arrow = "→" if "→" in m else "->"
                parts = [p.strip() for p in m.split(arrow)]
                parts = [p for p in parts if p]
                if len(parts) >= 2:
                    ids: list[str] = []
                    for token in parts:
                        # best-effort resolve to existing entity, else create component.
                        tid = _find_best_id_contains(token) or _ensure_component(token)
                        ids.append(tid)
                    for a, b in zip(ids, ids[1:], strict=False):
                        _add_relation(a, RelationType.LEADS_TO, b, rule_id="chain_leads_to")
                continue
    def _autolink_metrics_to_components(self, graph: CausalGraph, report_id: str, diff: AugmentDiff) -> None:
        """Add weak evidential edges to connect metric nodes to their component.

        Rationale:
        - Some extractors produce entities without relations, leaving "dead" nodes.
        - We only add INDICATES edges with low confidence and is_causal=false,
          so traversal-based root-cause reasoning can safely ignore them.
        """
        # Index components by normalized label for quick lookup.
        components: dict[str, str] = {}
        for e in graph.get_entities():
            if e.entity_type == EntityType.COMPONENT:
                norm = self._normalize_label(e.label)
                if norm:
                    components[norm] = e.id

        if not components:
            return

        existing_relation_keys = self._relation_keys(graph.get_relations())

        def _choose_component(metric: Entity) -> str | None:
            hay = f"{metric.label} {metric.source_text}".lower()
            # Heuristics for v1: map common metric prefixes to core components.
            if "vcore" in hay and "vcore" in components:
                return components["vcore"]
            if "ddr" in hay and "ddr" in components:
                return components["ddr"]
            if "cpu" in hay and "cpu" in components:
                return components["cpu"]
            if "mmdvfs" in hay and "mmdvfs" in components:
                return components["mmdvfs"]
            return None

        for e in graph.get_entities():
            if e.entity_type != EntityType.METRIC:
                continue

            target_component_id = _choose_component(e)
            if not target_component_id:
                continue

            key = (e.id, RelationType.INDICATES.value, target_component_id)
            if key in existing_relation_keys:
                continue

            rel = Relation(
                source_id=e.id,
                target_id=target_component_id,
                relation_type=RelationType.INDICATES,
                confidence=0.3,
                evidence="autolink_rule: metric indicates component",
                causal_effect=None,
                attributes={
                    "provenance": [
                        {
                            "source": "autolink_rule",
                            "report_id": report_id,
                            "reason": "connect_isolated_metric_to_component",
                        }
                    ]
                },
            )
            try:
                graph.add_relation(rel, validate_dag=False)
                existing_relation_keys.add(key)
                diff.added_relations.append(
                    {"source": e.id, "target": target_component_id, "type": RelationType.INDICATES.value}
                )
            except Exception as exc:
                diff.conflicts.append(str(exc))

    def _ensure_missing_entities(
        self,
        graph: CausalGraph,
        missing_labels: list[str],
        report_id: str,
        diff: AugmentDiff,
    ) -> None:
        if not missing_labels:
            return

        if diff.feedback_added_entities is None:
            diff.feedback_added_entities = []
        if diff.feedback_skipped_existing is None:
            diff.feedback_skipped_existing = []

        existing_by_norm = {self._normalize_label(e.label): e.id for e in graph.get_entities()}

        for label in missing_labels:
            norm = self._normalize_label(label)
            if not norm:
                continue
            if norm in existing_by_norm:
                diff.feedback_skipped_existing.append(existing_by_norm[norm])
                continue

            entity_type = infer_feedback_entity_type(label)
            entity_id = generate_feedback_entity_id(entity_type, label)
            # Ensure uniqueness in this graph (avoid ID collision)
            if graph.get_entity(entity_id) is not None:
                # fallback: salt with report_id (still deterministic within run)
                entity_id = generate_feedback_entity_id(entity_type, f"{label}:{report_id}")

            fb_prov = {
                "source": "closed_loop_feedback",
                "report_id": report_id,
                "label": label,
                "reason": "missing_elements",
            }
            new_entity = Entity(
                id=entity_id,
                entity_type=entity_type,
                label=label,
                description="",
                attributes={"provenance": [fb_prov]},
                confidence=1.0,
                source_text="",
            )
            graph.add_entity(new_entity)
            diff.feedback_added_entities.append(entity_id)
            existing_by_norm[norm] = entity_id

    def _build_entity_index(self, entities: list[Entity]) -> dict[tuple[str, str], str]:
        index: dict[tuple[str, str], str] = {}
        for entity in entities:
            norm = self._normalize_label(entity.label)
            index[(entity.entity_type.value, norm)] = entity.id
        return index

    def _index_entity(self, index: dict[tuple[str, str], str], entity: Entity) -> None:
        norm = self._normalize_label(entity.label)
        index[(entity.entity_type.value, norm)] = entity.id

    def _match_entity(
        self,
        entity: Entity,
        index: dict[tuple[str, str], str],
        existing_entities: list[Entity],
    ) -> str | None:
        norm = self._normalize_label(entity.label)
        key = (entity.entity_type.value, norm)
        if key in index:
            return index[key]

        if not self._fuzzy_match:
            return None

        best_id = None
        best_score = 0.0
        for existing in existing_entities:
            if existing.entity_type != entity.entity_type:
                continue
            score = self._similarity(norm, self._normalize_label(existing.label))
            if score > best_score:
                best_score = score
                best_id = existing.id
        if best_score >= self._similarity_threshold:
            return best_id
        return None

    def _merge_entity(
        self,
        graph: CausalGraph,
        entity_id: str,
        new_entity: Entity,
        report_id: str,
        diff: AugmentDiff,
    ) -> None:
        existing = graph.get_entity(entity_id)
        if existing is None:
            return

        updated = False
        if not existing.description and new_entity.description:
            existing.description = new_entity.description
            updated = True
        if new_entity.confidence > existing.confidence:
            existing.confidence = new_entity.confidence
            updated = True

        provenance = existing.attributes.get("provenance", [])
        provenance.append(self._build_provenance(report_id, new_entity.source_text))
        existing.attributes["provenance"] = provenance
        updated = True

        if updated:
            diff.updated_entities.append(entity_id)

    def _merge_relation(
        self,
        graph: CausalGraph,
        key: tuple[str, str, str],
        new_relation: Relation,
        report_id: str,
        diff: AugmentDiff,
    ) -> None:
        source_id, rel_type, target_id = key
        for relation in graph.get_relations():
            if (
                relation.source_id == source_id
                and relation.target_id == target_id
                and relation.relation_type.value == rel_type
            ):
                if new_relation.confidence > relation.confidence:
                    relation.confidence = new_relation.confidence
                if new_relation.evidence and new_relation.evidence not in relation.evidence:
                    if relation.evidence:
                        relation.evidence = f"{relation.evidence} | {new_relation.evidence}"
                    else:
                        relation.evidence = new_relation.evidence
                provenance = relation.attributes.get("provenance", [])
                provenance.append(self._build_provenance(report_id, new_relation.evidence))
                relation.attributes["provenance"] = provenance
                diff.updated_relations.append(
                    {"source": source_id, "target": target_id, "type": rel_type}
                )
                return

    def _relation_keys(self, relations: list[Relation]) -> set[tuple[str, str, str]]:
        return {(r.source_id, r.relation_type.value, r.target_id) for r in relations}

    def _generate_entity_id(self, entity: Entity, report_id: str) -> str:
        norm = self._normalize_label(entity.label)
        raw = f"{entity.entity_type.value}:{norm}:{report_id}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        return f"aug_{entity.entity_type.value.lower()}_{digest}"

    def _normalize_label(self, label: str) -> str:
        text = label.strip().lower()
        replacements = {
            "拉檔": "frequency throttling",
            "ddr 投票機制": "ddr voting",
            "投票機制": "voting",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        # Drop embedded percent values so metric nodes don't fragment across cases.
        # Examples: "vcore usage 82.6%" -> "vcore usage"
        text = re.sub(r"(?<![a-z0-9_])\d+(?:\.\d+)?\s*%(?![a-z0-9_])", " ", text)
        return " ".join(text.split())

    def _similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def _build_provenance(self, report_id: str, source_text: str) -> dict[str, str]:
        return {
            "report_id": report_id,
            "source_text": source_text or "",
        }

    @staticmethod
    def _canonicalize_metric_label(label: str) -> tuple[str, dict[str, Any]]:
        """Canonicalize metric labels by stripping volatile numeric percent values.

        Returns:
          (canonical_label, extra_attrs)
        """
        raw = (label or "").strip()
        if not raw:
            return "", {}

        # Extract percent-like numeric values (including long float strings).
        values: list[dict[str, str]] = []
        for m in re.finditer(r"(?P<num>\d+(?:\.\d+)?)(?P<unit>\s*%)", raw):
            num = m.group("num")
            unit = m.group("unit").strip() or "%"
            values.append({"value": f"{num}{unit}", "num": num, "unit": unit})

        # Remove only percent tokens; keep things like "725mV" intact.
        canon = re.sub(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?\s*%(?![A-Za-z0-9_])", " ", raw)
        canon = " ".join(canon.split()).strip(" -:;")
        # Cleanup dangling prepositions when % was removed.
        canon = re.sub(r"\b(at|of)\b\s*$", "", canon, flags=re.IGNORECASE).strip()

        extra: dict[str, Any] = {"raw_label": raw}
        if values:
            extra["metric_values"] = values
        return canon or raw, extra


def load_ckg(path: str | Path) -> CausalGraph:
    data = Path(path).read_text(encoding="utf-8")
    return CausalGraph.from_json(data)


def save_ckg(graph: CausalGraph, path: str | Path) -> None:
    Path(path).write_text(graph.to_json(indent=2), encoding="utf-8")


def load_or_init_ckg(path: str | Path | None, init_empty: bool) -> CausalGraph:
    if path and init_empty:
        raise ValueError("Provide either --ckg or --init-empty, not both.")
    if path:
        return load_ckg(path)
    if init_empty:
        return CausalGraph()
    raise ValueError("No base CKG provided. Use --ckg or --init-empty.")


def extract_missing_elements(feedback: dict[str, Any], case_filter: str = "all") -> list[str]:
    """Extract missing elements from orchestrator feedback (minimal v1 dependency)."""
    per_case = feedback.get("per_case", {}) or {}
    wanted_cases: list[str]
    if case_filter == "all":
        wanted_cases = list(per_case.keys())
    else:
        wanted_cases = [case_filter]

    missing: list[str] = []
    for case_id in wanted_cases:
        case_obj = per_case.get(case_id, {}) or {}
        for dim in case_obj.get("dimensions", []) or []:
            missing.extend(dim.get("missing_elements", []) or [])
    # stable de-dup while preserving order
    seen = set()
    out = []
    for m in missing:
        if not isinstance(m, str):
            continue
        key = m.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def infer_feedback_entity_type(label: str) -> EntityType:
    """Heuristic v1: choose a safe default type for feedback-added labels."""
    norm = label.strip().lower()
    if norm.startswith("sw_req"):
        return EntityType.OBSERVATION
    if "vcore" in norm or "ddr" in norm or "%" in norm:
        return EntityType.METRIC
    return EntityType.OBSERVATION


def generate_feedback_entity_id(entity_type: EntityType, label: str) -> str:
    norm = " ".join(label.strip().lower().split())
    raw = f"fb:{entity_type.value}:{norm}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"fb_{entity_type.value.lower()}_{digest}"
