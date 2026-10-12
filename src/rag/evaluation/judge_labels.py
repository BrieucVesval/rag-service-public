"""Human labels to validate the LLM judge: blind sample export, label parsing, agreement.

An LLM judge is a measuring instrument; its metrics are only trusted once its verdicts
agree with a human's on a sample. The sample is:
- stratified: every non-"supported" sentence verdict and every non-"present" key-fact
  verdict, every verdict that changed between two judge runs, plus a few random
  "supported"/"present" ones. A uniform sample would be almost all "supported" and make
  agreement look high without testing the hard cases;
- blind: the judge's verdicts are not in the file, to avoid anchoring the human;
- grouped by question, and random "supported" sentences are drawn from questions
  already sampled, so fewer source contexts have to be read.

Agreement is reported as raw agreement, Cohen's kappa (agreement corrected for chance)
and a confusion matrix, on all verdict classes and on the binary decision each metric
uses (supported vs. not for faithfulness, present vs. not for correctness).
"""

import random
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from rag.evaluation.judge import (
    CORRECTNESS_SYSTEM_PROMPT,
    FAITHFULNESS_SYSTEM_PROMPT,
    FactVerdict,
    SupportVerdict,
)
from rag.evaluation.judge_eval import REFUSAL_REASON, QuestionJudgment
from rag.generation.citations import strip_citations
from rag.generation.prompts import format_context
from rag.models import Answer

SENTENCE_PREFIX = "S"
FACT_PREFIX = "F"
_ITEM_HEADING = re.compile(r"^### ([SF])-(q\d+)-(\d+)\s*$")
_LABEL_LINE = re.compile(r"^- Label:\s*(\S*)\s*$")


class LabelItem(BaseModel):
    """One verdict to label: a sentence (S) or a key fact (F) of one question."""

    kind: str
    question_id: str
    item_id: int

    @property
    def key(self) -> str:
        return f"{self.kind}-{self.question_id}-{self.item_id}"


def select_sample(
    reference: Sequence[QuestionJudgment],
    other: Sequence[QuestionJudgment] | None,
    n_random_supported: int,
    n_random_present: int,
    seed: int,
) -> list[LabelItem]:
    """Stratified sample of judge verdicts to label (see module docstring)."""
    rng = random.Random(seed)
    other_by_id = {j.question_id: j for j in other or []}
    chosen: set[tuple[str, str, int]] = set()

    for judgment in reference:
        flipped = other_by_id.get(judgment.question_id)
        for s in judgment.sentences:
            changed = flipped is not None and _sentence_verdict(flipped, s.id) not in (
                None,
                s.verdict,
            )
            if s.verdict not in (SupportVerdict.SUPPORTED, SupportVerdict.NO_CLAIM) or changed:
                chosen.add((SENTENCE_PREFIX, judgment.question_id, s.id))
        for f in judgment.key_facts:
            if f.reason == REFUSAL_REASON:
                continue  # scored 0 by rule, not by the judge
            changed = flipped is not None and _fact_verdict(flipped, f.id) not in (None, f.verdict)
            if f.verdict != FactVerdict.PRESENT or changed:
                chosen.add((FACT_PREFIX, judgment.question_id, f.id))

    sampled_questions = {question_id for _, question_id, _ in chosen}
    supported = [
        (SENTENCE_PREFIX, j.question_id, s.id)
        for j in reference
        if j.question_id in sampled_questions
        for s in j.sentences
        if s.verdict == SupportVerdict.SUPPORTED
        and (SENTENCE_PREFIX, j.question_id, s.id) not in chosen
    ]
    present = [
        (FACT_PREFIX, j.question_id, f.id)
        for j in reference
        for f in j.key_facts
        if f.verdict == FactVerdict.PRESENT and (FACT_PREFIX, j.question_id, f.id) not in chosen
    ]
    chosen.update(rng.sample(supported, min(n_random_supported, len(supported))))
    chosen.update(rng.sample(present, min(n_random_present, len(present))))

    order = {j.question_id: index for index, j in enumerate(reference)}
    return [
        LabelItem(kind=kind, question_id=question_id, item_id=item_id)
        for kind, question_id, item_id in sorted(
            chosen, key=lambda c: (order[c[1]], c[0] != SENTENCE_PREFIX, c[2])
        )
    ]


def render_label_file(
    items: Sequence[LabelItem],
    judgments: dict[str, QuestionJudgment],
    answers: dict[str, Answer],
    header: str,
) -> str:
    """Markdown file to fill in: one section per question, sources folded, no judge verdict."""
    lines = [header, "", *_instructions(), ""]
    for question_id in dict.fromkeys(item.question_id for item in items):
        judgment, answer = judgments[question_id], answers[question_id]
        lines += [f"## {question_id} — {judgment.question}", ""]
        group = [item for item in items if item.question_id == question_id]
        if any(item.kind == SENTENCE_PREFIX for item in group):
            lines += [
                "<details><summary>Sources given to the assistant</summary>",
                "",
                format_context(answer.retrieved),
                "",
                "</details>",
                "",
            ]
        lines += [
            "<details><summary>Full answer</summary>",
            "",
            answer.text,
            "",
            "</details>",
            "",
        ]
        for item in group:
            lines += [f"### {item.key}", ""]
            if item.kind == SENTENCE_PREFIX:
                sentence = next(s for s in judgment.sentences if s.id == item.item_id)
                lines.append(f"Sentence: {strip_citations(sentence.text)}")
                lines.append(f"Labels: {', '.join(v.value for v in SupportVerdict)}")
            else:
                fact = next(f for f in judgment.key_facts if f.id == item.item_id)
                lines.append(f"Reference fact: {fact.fact}")
                lines.append(f"Labels: {', '.join(v.value for v in FactVerdict)}")
            lines += ["", "- Label: ", "- Note: ", ""]
    return "\n".join(lines)


def parse_labels(text: str) -> tuple[dict[str, str], list[str]]:
    """Labels by item key, and problems (missing or unknown labels)."""
    labels: dict[str, str] = {}
    problems: list[str] = []
    current: tuple[str, str] | None = None  # (key, kind)
    for line in text.splitlines():
        heading = _ITEM_HEADING.match(line)
        if heading:
            kind, question_id, item_id = heading.groups()
            current = (f"{kind}-{question_id}-{item_id}", kind)
            continue
        label = _LABEL_LINE.match(line)
        if label and current is not None:
            key, kind = current
            value = label.group(1).strip().lower()
            allowed = _allowed(kind)
            if not value:
                problems.append(f"{key}: no label")
            elif value not in allowed:
                problems.append(f"{key}: unknown label {value!r} (allowed: {sorted(allowed)})")
            else:
                labels[key] = value
            current = None
    return labels, problems


def judge_verdicts(judgments: Iterable[QuestionJudgment]) -> dict[str, str]:
    """Every verdict of a judge run, keyed like label items ("S-q001-2", "F-q001-1")."""
    verdicts: dict[str, str] = {}
    for j in judgments:
        for s in j.sentences:
            verdicts[f"{SENTENCE_PREFIX}-{j.question_id}-{s.id}"] = s.verdict.value
        for f in j.key_facts:
            verdicts[f"{FACT_PREFIX}-{j.question_id}-{f.id}"] = f.verdict.value
    return verdicts


def adjudication_sample(
    items: Sequence[LabelItem],
    first: dict[str, str],
    second: dict[str, str],
    n_agreements: int,
    seed: int,
) -> list[LabelItem]:
    """Items for a human to adjudicate: every disagreement between two raters, plus a
    random audit of agreements (two LLMs can be wrong the same way). Order is kept."""
    labelled = [item for item in items if item.key in first and item.key in second]
    disagreements = {item.key for item in labelled if first[item.key] != second[item.key]}
    agreements = [item.key for item in labelled if item.key not in disagreements]
    audit = set(random.Random(seed).sample(agreements, min(n_agreements, len(agreements))))
    return [item for item in labelled if item.key in disagreements | audit]


class Agreement(BaseModel):
    n: int
    agreement: float
    kappa: float | None
    confusion: dict[str, dict[str, int]]  # human label -> judge label -> count


def agreement(pairs: Sequence[tuple[str, str]]) -> Agreement:
    """Raw agreement and Cohen's kappa between (human, judge) labels."""
    n = len(pairs)
    observed = sum(human == judge for human, judge in pairs) / n
    human_counts = Counter(human for human, _ in pairs)
    judge_counts = Counter(judge for _, judge in pairs)
    expected = sum(human_counts[k] * judge_counts[k] for k in human_counts) / (n * n)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    confusion: dict[str, dict[str, int]] = {}
    for human, judge in pairs:
        confusion.setdefault(human, {}).setdefault(judge, 0)
        confusion[human][judge] += 1
    return Agreement(n=n, agreement=observed, kappa=kappa, confusion=confusion)


def binarize(pairs: Iterable[tuple[str, str]], positive: str) -> list[tuple[str, str]]:
    """Collapse labels to the decision a metric uses, e.g. supported vs. not."""
    other = f"not_{positive}"
    return [(h if h == positive else other, j if j == positive else other) for h, j in pairs]


def _sentence_verdict(judgment: QuestionJudgment, sentence_id: int) -> SupportVerdict | None:
    return next((s.verdict for s in judgment.sentences if s.id == sentence_id), None)


def _fact_verdict(judgment: QuestionJudgment, fact_id: int) -> FactVerdict | None:
    return next((f.verdict for f in judgment.key_facts if f.id == fact_id), None)


def _allowed(kind: str) -> set[str]:
    verdicts = SupportVerdict if kind == SENTENCE_PREFIX else FactVerdict
    return {v.value for v in verdicts}


def _instructions() -> list[str]:
    """The judge's own rubric, so human and judge apply the same definitions."""
    return [
        "Label each item blind: the judge's verdict is deliberately not shown.",
        "Fill in `- Label:` with one of the allowed labels; `- Note:` is optional.",
        "",
        "<details><summary>Rubric for sentences (S-…): same as the judge</summary>",
        "",
        "```text",
        FAITHFULNESS_SYSTEM_PROMPT,
        "```",
        "",
        "</details>",
        "",
        "<details><summary>Rubric for reference facts (F-…): same as the judge</summary>",
        "",
        "```text",
        CORRECTNESS_SYSTEM_PROMPT,
        "```",
        "",
        "</details>",
    ]
