"""Task 5: LLM-as-a-Judge with Pydantic structured output."""

from pydantic import BaseModel
from enum import Enum
from openai import OpenAI
from .config import OPENAI_API_KEY, JUDGE_MODEL
from .rubric import RUBRIC, JUDGE_CRITERIA


client = OpenAI(api_key=OPENAI_API_KEY)


class Verdict(str, Enum):
    good = "good"
    ok = "ok"
    bad = "bad"


class CriterionResult(BaseModel):
    explanation: str  # explanation BEFORE verdict -> forces chain-of-thought
    verdict: Verdict


class JudgeOutput(BaseModel):
    fluency: CriterionResult
    grammar: CriterionResult
    tone: CriterionResult
    length: CriterionResult
    grounding: CriterionResult


class SingleCriterionOutput(BaseModel):
    explanation: str
    verdict: Verdict


def _build_rubric_text() -> str:
    """Format the rubric for inclusion in the judge prompt."""
    lines = []
    for criterion in JUDGE_CRITERIA:
        defn = RUBRIC[criterion]
        lines.append(f"### {criterion.title()}")
        lines.append(f"  - good: {defn['good']}")
        lines.append(f"  - ok: {defn['ok']}")
        lines.append(f"  - bad: {defn['bad']}")
    return "\n".join(lines)


JUDGE_SYSTEM_PROMPT = f"""\
You are a strict product-description evaluator. You will be given:
1. The product information (name, attributes, material, warranty)
2. A generated description to evaluate

Rate the description on each criterion below using EXACTLY the definitions provided.
For each criterion, first explain your reasoning, then give a verdict (good / ok / bad).

## Rubric
{_build_rubric_text()}

Be precise. Apply the rubric exactly as written."""


def judge_all_criteria(product: dict, description: str, model: str = JUDGE_MODEL) -> dict:
    """Judge a description on all criteria at once.

    Returns dict mapping criterion -> {explanation, verdict}
    """
    user_prompt = (
        f"## Product Information\n"
        f"Name: {product['product_name']}\n"
        f"Attributes: {product['Product_attribute_list']}\n"
        f"Material: {product['material']}\n"
        f"Warranty: {product['warranty']}\n\n"
        f"## Generated Description\n{description}"
    )

    response = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=JudgeOutput,
        temperature=0.0,
    )

    result = response.choices[0].message.parsed
    return {
        criterion: {
            "explanation": getattr(result, criterion).explanation,
            "verdict": getattr(result, criterion).verdict.value,
        }
        for criterion in JUDGE_CRITERIA
    }


def judge_single_criterion(
    product: dict, description: str, criterion: str, model: str = JUDGE_MODEL
) -> dict:
    """Judge a description on a single criterion (Task 6.4).

    Returns dict with {explanation, verdict}
    """
    defn = RUBRIC[criterion]
    system_prompt = (
        f"You are a strict product-description evaluator.\n"
        f"Evaluate ONLY the '{criterion}' criterion.\n\n"
        f"## {criterion.title()} Rubric\n"
        f"  - good: {defn['good']}\n"
        f"  - ok: {defn['ok']}\n"
        f"  - bad: {defn['bad']}\n\n"
        f"First explain your reasoning, then give a verdict (good / ok / bad)."
    )

    user_prompt = (
        f"## Product Information\n"
        f"Name: {product['product_name']}\n"
        f"Attributes: {product['Product_attribute_list']}\n"
        f"Material: {product['material']}\n"
        f"Warranty: {product['warranty']}\n\n"
        f"## Generated Description\n{description}"
    )

    response = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=SingleCriterionOutput,
        temperature=0.0,
    )

    result = response.choices[0].message.parsed
    return {
        "explanation": result.explanation,
        "verdict": result.verdict.value,
    }
