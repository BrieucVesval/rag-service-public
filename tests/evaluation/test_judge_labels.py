import pytest

from rag.evaluation.golden_set import Category
from rag.evaluation.judge import FactVerdict, SupportVerdict
from rag.evaluation.judge_eval import (
    REFUSAL_REASON,
    KeyFactJudgment,
    QuestionJudgment,
    SentenceJudgment,
)
from rag.evaluation.judge_labels import (
    LabelItem,
    adjudication_sample,
    agreement,
    binarize,
    fleiss_kappa,
    judge_verdicts,
    majority_label,
    parse_labels,
    relabel,
    render_label_file,
    select_sample,
)
from rag.models import RetrievedChunk
from tests.evaluation.test_generation_eval import make_answer


def judgment(
    question_id: str,
    sentences: list[SupportVerdict],
    facts: list[FactVerdict] = (),  # type: ignore[assignment]
    fact_reason: str = "r",
) -> QuestionJudgment:
    return QuestionJudgment(
        question_id=question_id,
        question=f"Question {question_id} ?",
        category=Category.LOOKUP,
        split="dev",
        refused=False,
        sentences=[
            SentenceJudgment(
                id=i,
                text=f"Phrase {i} [1].",
                cited=[1],
                reason="secret reason",
                verdict=v,
                supporting_blocks=[],
            )
            for i, v in enumerate(sentences, start=1)
        ],
        key_facts=[
            KeyFactJudgment(id=i, fact=f"Fait {i}", reason=fact_reason, verdict=v)
            for i, v in enumerate(facts, start=1)
        ],
    )


S, U, N = SupportVerdict.SUPPORTED, SupportVerdict.UNSUPPORTED, SupportVerdict.NO_CLAIM


def keys(items) -> list[str]:  # type: ignore[no-untyped-def]
    return [item.key for item in items]


def test_sample_takes_hard_cases_flips_and_random_supported_from_sampled_questions() -> None:
    reference = [
        judgment("q001", [S, U, N, S, S]),
        judgment("q002", [S, S, S], [FactVerdict.PRESENT, FactVerdict.ABSENT]),
        judgment("q003", [S, S]),  # nothing hard, nothing flipped: never sampled
    ]
    other = [judgment("q001", [S, U, N, S, S]), judgment("q002", [S, U, S])]

    items = select_sample(reference, other, n_random_supported=2, n_random_present=0, seed=0)

    assert {"S-q001-2", "S-q002-2", "F-q002-2"} <= set(keys(items))  # unsupported, flip, absent
    assert not any(item.question_id == "q003" for item in items)
    assert "S-q001-3" not in keys(items)  # no_claim is not a hard case
    assert len(items) == 5
    assert select_sample(reference, other, 2, 0, seed=0) == items  # deterministic


def test_refusal_facts_are_not_sampled() -> None:
    reference = [judgment("q001", [], [FactVerdict.ABSENT], fact_reason=REFUSAL_REASON)]

    assert select_sample(reference, None, 0, 0, seed=0) == []


def test_label_file_is_blind_and_round_trips(retrieved: list[RetrievedChunk]) -> None:
    reference = [judgment("q001", [S, U], [FactVerdict.CONTRADICTED])]
    items = select_sample(reference, None, 1, 0, seed=0)
    answer = make_answer("Question q001 ?").model_copy(update={"retrieved": retrieved})

    text = render_label_file(items, {"q001": reference[0]}, {"q001": answer}, "# Labels")

    assert "secret reason" not in text
    assert "contradicted" not in text.split("### ")[1].split("Labels:")[0]  # no verdict shown
    assert "Sentence: Phrase 2." in text  # markers removed, as for the judge
    assert "[3] Titre F2" in text  # sources included
    filled = text.replace("- Label: ", "- Label: supported", 1)  # first item: S-q001-1
    labels, problems = parse_labels(filled)
    assert labels == {"S-q001-1": "supported"}
    assert problems == ["S-q001-2: no label", "F-q001-1: no label"]


def test_unknown_label_is_reported() -> None:
    labels, problems = parse_labels("### F-q001-1\n- Label: supported\n")

    assert labels == {}
    assert "unknown label 'supported'" in problems[0]


def test_agreement_and_cohen_kappa() -> None:
    pairs = [("a", "a"), ("a", "a"), ("b", "b"), ("b", "a")]

    result = agreement(pairs)

    # observed 0.75; expected = (2*3 + 2*1) / 16 = 0.5; kappa = 0.25 / 0.5
    assert result.agreement == 0.75
    assert result.kappa == pytest.approx(0.5)
    assert result.confusion == {"a": {"a": 2}, "b": {"b": 1, "a": 1}}


def test_kappa_undefined_when_both_raters_use_one_label() -> None:
    assert agreement([("a", "a"), ("a", "a")]).kappa is None


def test_binarize_keeps_the_metric_decision() -> None:
    pairs = [("supported", "partial"), ("unsupported", "contradicted")]

    assert binarize(pairs, "supported") == [
        ("supported", "not_supported"),
        ("not_supported", "not_supported"),
    ]


def test_judge_verdicts_are_keyed_like_label_items() -> None:
    verdicts = judge_verdicts([judgment("q001", [S, U], [FactVerdict.PARTIAL])])

    assert verdicts == {"S-q001-1": "supported", "S-q001-2": "unsupported", "F-q001-1": "partial"}


def test_adjudication_takes_all_disagreements_and_audits_some_agreements() -> None:
    items = [LabelItem(kind="S", question_id="q001", item_id=i) for i in range(1, 7)]
    llm = {item.key: "supported" for item in items}
    judge = {**llm, "S-q001-2": "unsupported", "S-q001-5": "partial"}

    selected = adjudication_sample(items, llm, judge, n_agreements=2, seed=0)

    keys = [item.key for item in selected]
    assert {"S-q001-2", "S-q001-5"} <= set(keys)
    assert len(keys) == 4
    assert keys == sorted(keys)  # question order kept: disagreements are not grouped first
    assert adjudication_sample(items, llm, judge, 2, seed=0) == selected


def test_majority_needs_more_than_half() -> None:
    assert majority_label(["supported", "partial", "supported"]) == "supported"
    assert majority_label(["supported", "partial", "unsupported"]) is None
    assert majority_label(["supported", "partial"]) is None
    assert majority_label([]) is None


def test_fleiss_kappa() -> None:
    assert fleiss_kappa([["a", "a", "a"], ["b", "b", "b"]]) == pytest.approx(1.0)
    # Textbook-style check: 2 raters, Fleiss reduces to Scott's pi.
    ratings = [["a", "a"], ["a", "b"], ["b", "b"], ["a", "a"]]
    observed = 3 / 4
    expected = (5 / 8) ** 2 + (3 / 8) ** 2
    assert fleiss_kappa(ratings) == pytest.approx((observed - expected) / (1 - expected))
    assert fleiss_kappa([["a", "a"], ["a", "a"]]) is None  # one label only
    assert fleiss_kappa([["a", "a"], ["a"]]) is None  # unequal raters


def test_relabel_recomputes_metrics_and_bounds_citations() -> None:
    j = judgment("q001", [S, U], [FactVerdict.ABSENT, FactVerdict.PRESENT])
    j = j.model_copy(
        update={
            "sentences": [
                j.sentences[0].model_copy(update={"supporting_blocks": [1]}),
                j.sentences[1],
            ]
        }
    )
    labels = {"S-q001-1": "unsupported", "S-q001-2": "supported", "F-q001-1": "partial"}

    upper = relabel([j], labels, newly_supported_cite_correctly=True)[0]
    lower = relabel([j], labels, newly_supported_cite_correctly=False)[0]

    assert upper.faithfulness == 0.5
    assert upper.correctness == 0.75
    assert upper.sentences[0].supporting_blocks == []
    assert upper.sentences[1].supporting_blocks == [1]
    assert upper.citation_accuracy == 0.5
    assert lower.citation_accuracy == 0.0
    assert j.sentences[1].verdict == U  # input untouched
