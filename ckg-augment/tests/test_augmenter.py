from __future__ import annotations

from dataclasses import dataclass

from ckg_augment.augmenter import CkgAugmenter
from src.graph.models import CausalGraph, Entity, EntityType, Relation, RelationType


@dataclass
class FakeEntityExtractor:
    entities: list[Entity]

    def extract_entities(self, text: str) -> list[Entity]:
        return self.entities


@dataclass
class FakeRelationExtractor:
    relations: list[Relation]

    def extract_relations(self, text: str, entities: list[Entity]) -> list[Relation]:
        return self.relations


def test_augment_adds_new_entity_and_relation():
    base = CausalGraph()
    base.add_entity(
        Entity(
            id="rc_cm",
            entity_type=EntityType.ROOT_CAUSE,
            label="CM",
            description="CPU Manager",
        )
    )

    extracted_entities = [
        Entity(
            id="e1",
            entity_type=EntityType.ROOT_CAUSE,
            label="CM",
            description="CPU Manager",
        ),
        Entity(
            id="e2",
            entity_type=EntityType.COMPONENT,
            label="DDR voting",
            description="DDR voting mechanism",
        ),
    ]

    extracted_relations = [
        Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
            confidence=0.8,
            evidence="CM drives DDR voting",
        )
    ]

    augmenter = CkgAugmenter(
        entity_extractor=FakeEntityExtractor(extracted_entities),
        relation_extractor=FakeRelationExtractor(extracted_relations),
        fuzzy_match=False,
    )

    augmented, diff = augmenter.augment(
        report_text="CM drives DDR voting",
        base_ckg=base,
        report_id="test_report",
    )

    assert len(augmented.get_entities()) == 2
    assert len(diff.added_entities) == 1
    assert "rc_cm" in diff.updated_entities
    assert len(diff.added_relations) == 1


def test_feedback_missing_element_adds_entity():
    base = CausalGraph()
    base.add_entity(
        Entity(
            id="rc_cm",
            entity_type=EntityType.ROOT_CAUSE,
            label="CM",
            description="CPU Manager",
        )
    )

    augmenter = CkgAugmenter(
        entity_extractor=FakeEntityExtractor([]),
        relation_extractor=FakeRelationExtractor([]),
        fuzzy_match=False,
    )

    feedback = {
        "run_id": "r1",
        "iter_num": 1,
        "per_case": {
            "case1": {
                "dimensions": [
                    {"name": "Causal Chain Completeness", "missing_elements": ["SW_REQ2"]},
                ]
            }
        },
    }

    augmented, diff = augmenter.augment(
        report_text="",
        base_ckg=base,
        report_id="test_report",
        feedback=feedback,
        case_filter="case1",
    )

    labels = {e.label for e in augmented.get_entities()}
    assert "SW_REQ2" in labels
    assert diff.feedback_added_entities is not None
    assert len(diff.feedback_added_entities) == 1


def test_feedback_idempotent_no_duplicates():
    base = CausalGraph()
    augmenter = CkgAugmenter(
        entity_extractor=FakeEntityExtractor([]),
        relation_extractor=FakeRelationExtractor([]),
        fuzzy_match=False,
    )
    feedback = {
        "per_case": {"case1": {"dimensions": [{"missing_elements": ["SW_REQ2"]}]}}
    }

    augmented1, diff1 = augmenter.augment(
        report_text="",
        base_ckg=base,
        report_id="r",
        feedback=feedback,
        case_filter="case1",
    )
    augmented2, diff2 = augmenter.augment(
        report_text="",
        base_ckg=augmented1,
        report_id="r",
        feedback=feedback,
        case_filter="case1",
    )

    labels2 = [e.label for e in augmented2.get_entities()]
    assert labels2.count("SW_REQ2") == 1
    assert diff1.feedback_added_entities is not None and len(diff1.feedback_added_entities) == 1
    assert diff2.feedback_added_entities is not None and len(diff2.feedback_added_entities) == 0


def _relation_keys(graph: CausalGraph) -> set[tuple[str, str, str]]:
    return {(r.source_id, r.relation_type.value, r.target_id) for r in graph.get_relations()}


def test_feedback_adds_sw_req_relations_and_throttle():
    base = CausalGraph()
    # Existing CM root cause node is usually not labeled exactly "CM" in augmented graphs,
    # so test the "contains" resolver.
    base.add_entity(Entity(id="rc_cm_1", entity_type=EntityType.ROOT_CAUSE, label="CM causing VCORE increase"))
    base.add_entity(Entity(id="comp_powerhal", entity_type=EntityType.COMPONENT, label="PowerHal"))

    augmenter = CkgAugmenter(
        entity_extractor=FakeEntityExtractor([]),
        relation_extractor=FakeRelationExtractor([]),
        fuzzy_match=False,
    )

    feedback = {
        "run_id": "r1",
        "iter_num": 1,
        "per_case": {
            "case2": {
                "dimensions": [
                    {"name": "Causal Chain Completeness", "missing_elements": ["SW_REQ2", "SW_REQ3"]},
                    {"name": "Root Cause Accuracy", "missing_elements": ["拉檔 (frequency throttling)"]},
                ]
            }
        },
    }

    augmented, diff = augmenter.augment(
        report_text="",
        base_ckg=base,
        report_id="r_case2",
        feedback=feedback,
        case_filter="case2",
    )

    # Entities added
    labels = {e.label for e in augmented.get_entities()}
    assert "SW_REQ2" in labels
    assert "SW_REQ3" in labels
    assert "拉檔" in labels

    # Relations added (all should be non-causal types)
    keys = _relation_keys(augmented)
    # Find the created entity IDs by label
    by_label = {e.label: e.id for e in augmented.get_entities()}
    assert (by_label["SW_REQ2"], RelationType.INDICATES.value, "rc_cm_1") in keys
    assert (by_label["SW_REQ3"], RelationType.INDICATES.value, "comp_powerhal") in keys
    assert (by_label["拉檔"], RelationType.INDICATES.value, "rc_cm_1") in keys

    assert diff.feedback_added_relations is not None
    assert len(diff.feedback_added_relations) >= 3


def test_feedback_chain_phrase_adds_leads_to_idempotent():
    base = CausalGraph()
    # Provide core components
    base.add_entity(Entity(id="c_cm", entity_type=EntityType.COMPONENT, label="CM"))
    base.add_entity(Entity(id="c_cpu", entity_type=EntityType.COMPONENT, label="CPU"))
    base.add_entity(Entity(id="c_ddr", entity_type=EntityType.COMPONENT, label="DDR"))
    base.add_entity(Entity(id="c_vcore", entity_type=EntityType.COMPONENT, label="VCORE"))

    augmenter = CkgAugmenter(
        entity_extractor=FakeEntityExtractor([]),
        relation_extractor=FakeRelationExtractor([]),
        fuzzy_match=False,
    )

    feedback = {
        "per_case": {
            "case2": {
                "dimensions": [
                    {"name": "Causal Chain Completeness", "missing_elements": ["CM → CPU → DDR → VCORE"]},
                ]
            }
        }
    }

    g1, d1 = augmenter.augment(
        report_text="",
        base_ckg=base,
        report_id="r",
        feedback=feedback,
        case_filter="case2",
    )
    keys1 = _relation_keys(g1)
    assert ("c_cm", RelationType.LEADS_TO.value, "c_cpu") in keys1
    assert ("c_cpu", RelationType.LEADS_TO.value, "c_ddr") in keys1
    assert ("c_ddr", RelationType.LEADS_TO.value, "c_vcore") in keys1
    assert d1.feedback_added_relations is not None and len(d1.feedback_added_relations) >= 3

    g2, d2 = augmenter.augment(
        report_text="",
        base_ckg=g1,
        report_id="r",
        feedback=feedback,
        case_filter="case2",
    )
    # No duplicates added on second pass
    assert d2.feedback_added_relations is not None and len(d2.feedback_added_relations) == 0
