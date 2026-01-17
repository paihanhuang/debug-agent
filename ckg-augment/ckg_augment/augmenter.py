"""CKG Augmenter: merge new report knowledge into an existing CKG."""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.extraction.entity_extractor import EntityExtractor
from src.extraction.relation_extractor import RelationExtractor
from src.graph.models import CausalGraph, Entity, Relation, RelationType


@dataclass
class AugmentDiff:
    added_entities: list[str]
    updated_entities: list[str]
    added_relations: list[dict[str, str]]
    updated_relations: list[dict[str, str]]
    skipped_relations: list[dict[str, str]]
    conflicts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_entities": self.added_entities,
            "updated_entities": self.updated_entities,
            "added_relations": self.added_relations,
            "updated_relations": self.updated_relations,
            "skipped_relations": self.skipped_relations,
            "conflicts": self.conflicts,
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
    ) -> tuple[CausalGraph, AugmentDiff]:
        """Augment base CKG with report-derived knowledge."""
        diff = AugmentDiff(
            added_entities=[],
            updated_entities=[],
            added_relations=[],
            updated_relations=[],
            skipped_relations=[],
            conflicts=[],
        )

        extracted_entities = self._entity_extractor.extract_entities(report_text)
        extracted_relations = self._relation_extractor.extract_relations(
            report_text, extracted_entities
        )

        existing_entities = list(base_ckg.get_entities())
        entity_index = self._build_entity_index(existing_entities)

        id_map: dict[str, str] = {}
        for entity in extracted_entities:
            matched_id = self._match_entity(entity, entity_index, existing_entities)
            if matched_id:
                id_map[entity.id] = matched_id
                self._merge_entity(base_ckg, matched_id, entity, report_id, diff)
            else:
                new_id = self._generate_entity_id(entity, report_id)
                id_map[entity.id] = new_id
                new_entity = Entity(
                    id=new_id,
                    entity_type=entity.entity_type,
                    label=entity.label,
                    description=entity.description,
                    attributes=self._build_provenance(report_id, entity.source_text),
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

        return base_ckg, diff

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
        return " ".join(text.split())

    def _similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def _build_provenance(self, report_id: str, source_text: str) -> dict[str, str]:
        return {
            "report_id": report_id,
            "source_text": source_text or "",
        }


def load_ckg(path: str | Path) -> CausalGraph:
    data = Path(path).read_text(encoding="utf-8")
    return CausalGraph.from_json(data)


def save_ckg(graph: CausalGraph, path: str | Path) -> None:
    Path(path).write_text(graph.to_json(indent=2), encoding="utf-8")
