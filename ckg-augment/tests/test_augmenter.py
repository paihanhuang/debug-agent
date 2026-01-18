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
