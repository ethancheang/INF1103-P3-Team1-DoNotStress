"""AIResponseSchema: the fields and allowed values of one Gemini reply."""

from __future__ import annotations

from typing import ClassVar


class AIResponseSchema:
    """The JSON contract between the prompt and the response validator.

    PromptBuilder tells Gemini about these fields and ResponseValidator
    checks them, so both read the same lists from here.
    """

    RAW_ANSWER_KEYS: ClassVar[tuple[str, ...]] = (
        "pss_1", "pss_2", "pss_3", "pss_4",
        "sleep_hours_avg", "sleep_quality",
        "pas_workload", "pas_catchup",
        "fin_stress",
        "mspss_friends", "mspss_family",
    )
    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "scored_items", "stress_score", "risk_category", "primary_stressors",
        "confidence", "reasoning", "soft_label", "tips", "speak_prominence",
    )
    SOFT_LABELS: ClassVar[tuple[str, ...]] = ("You're doing ok", "Worth a check-in", "Please reach out")
    SPEAK_PROMINENCE: ClassVar[tuple[str, ...]] = ("low", "medium", "high")
    RISK_CATEGORIES: ClassVar[frozenset[str]] = frozenset({"Low", "Moderate", "High"})
    PRIMARY_STRESSORS: ClassVar[frozenset[str]] = frozenset({
        "academic_overload", "low_social_support", "high_stress",
        "financial_pressure", "sleep_deprivation",
    })
    TIP_IDS: ClassVar[frozenset[str]] = frozenset({
        "rest_a_little_more", "workload_chunks", "sleep_routine",
        "keep_social_contact", "talk_to_someone", "short_breaks", "money_worries",
    })
    STRESS_SCORE_MIN: ClassVar[float] = 1.0
    STRESS_SCORE_MAX: ClassVar[float] = 5.0
    ITEM_MIN: ClassVar[int] = 1
    ITEM_MAX: ClassVar[int] = 5
    MIN_TIPS: ClassVar[int] = 1
    MAX_TIPS: ClassVar[int] = 3
    # Marks a record whose AI fields came from Gemini (stored with the record).
    SOURCE: ClassVar[str] = "gemini"
