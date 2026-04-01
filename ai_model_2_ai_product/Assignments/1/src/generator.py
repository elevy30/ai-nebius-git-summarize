"""Task 2: Generate product descriptions using OpenAI API."""

import time
from openai import OpenAI
from .config import OPENAI_API_KEY, GENERATOR_MODEL


client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """\
You are an expert e-commerce copywriter. Write a persuasive product description \
based ONLY on the provided product information. The description must be between \
50 and 90 words. Use a friendly, credible sales voice. Do not invent features \
or claims not present in the input. Output ONLY the description text, nothing else."""


def build_user_prompt(product: dict) -> str:
    """Build the user prompt from product fields."""
    return (
        f"Product: {product['product_name']}\n"
        f"Attributes: {product['Product_attribute_list']}\n"
        f"Material: {product['material']}\n"
        f"Warranty: {product['warranty']}"
    )


def generate_description(product: dict, model: str = GENERATOR_MODEL, **kwargs) -> dict:
    """Generate a description for a single product.

    Returns dict with: generated_description, latency_ms, input_tokens, output_tokens
    """
    user_prompt = build_user_prompt(product)

    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 200),
    )
    latency_ms = (time.time() - start) * 1000

    choice = response.choices[0]
    usage = response.usage

    return {
        "generated_description": choice.message.content.strip(),
        "latency_ms": round(latency_ms, 1),
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
    }
