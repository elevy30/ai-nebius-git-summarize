# Assignment 1 - LLM Evaluation Plan

## Overview
Build an end-to-end LLM evaluation pipeline: generate product descriptions using OpenAI models, evaluate them manually and with an LLM judge, then iterate to improve.

**API:** OpenAI (key from `.env` file at project root)

**Dataset:** 50 e-commerce products (name, attributes, material, warranty)
**Due:** 5.4.26

---

## Task 1 - Define Rubric (15 pts)

Create explicit scoring framework with:

**Criterion definitions** (good / ok / bad) for each:

| Criterion | Good | Ok | Bad |
|-----------|------|----|-----|
| Fluency | Natural, easy-to-read, flows well | Readable but awkward phrasing | Hard to read, broken sentences |
| Grammar | No spelling/punctuation errors | 1-2 minor errors | 3+ errors or major mistakes |
| Tone | Friendly, credible sales voice | Mostly appropriate but inconsistent | Wrong tone (too formal, robotic, aggressive) |
| Length | 50-90 words | 40-49 or 91-110 words | Outside that range |
| Grounding | Only uses provided information | Mostly grounded, minor embellishment | Invents features or contradicts input |
| Latency | < 2s avg | 2-5s avg | > 5s avg |
| Cost | < $0.001 per call | $0.001-$0.005 per call | > $0.005 per call |

**Pass bar:** At least 4 good ratings and 0 bad ratings
**Go/no-go rules:** If Grounding != good → auto-fail

---

## Task 2 - Generate Descriptions (20 pts)

1. **Generator model:** **gpt-4o-mini** (cost-effective, good quality)
2. Write system prompt: persuasive 50-90 word product descriptions based on provided features
3. Call OpenAI API for all 50 products, collect per call:
   - `generated_description`
   - `latency_ms`
   - `input_tokens`
   - `output_tokens`
4. Save to `assignment_01.xlsx` with blank columns for each criterion + `final_score`

**Tech:** OpenAI Python SDK, pandas + openpyxl for Excel

---

## Task 3 - Manual (Human) Evaluation (10 pts)

1. Add `cost` column (USD) using model pricing (input vs output token rates)
2. Rate 10-15 products manually using Task 1 rubric
3. Apply pass/fail rules -> set `final_score`
4. Baseline analysis: which criteria performed best/worst

---

## Task 4 - Improvement Cycle (15 pts)

Iterate on weakest criteria. Options:
- **Prompt engineering** - few-shot examples, stricter constraints
- **Switch model** - try the other model, or a larger one (~30B)
- **Decoding params** - adjust temperature, top_p, top_k, max_new_tokens
- **Post-processing** - grammar check, length trimming

Document each experiment: what changed, why, new scores.

---

## Task 5 - Build Judge Model (20 pts)

1. **Model:** Use a different OpenAI model than Task 2 (e.g., **gpt-4o** as judge if gpt-4o-mini was generator)
2. **Judge prompt:** Include full rubric definitions; provide product features for Grounding eval. Exclude cost and latency (measured programmatically)
3. **Pydantic output schema:** Per criterion -> `{explanation: str, verdict: good/ok/bad}` (explanation BEFORE verdict - forces chain-of-thought before decision)
4. Use structured output support in the API

---

## Task 6 - Run & Analyze Judge (20 pts)

1. **Sanity check** - run judge on 5 products, manually verify
2. **Full run** - all 50 products, compute final_score
3. **Compare to human** - agreement rate per criterion, analyze divergences
4. **Criterion-by-criterion judging** - one API call per criterion per product, compare to batch judging
5. **Analysis** - trade-offs (cost, scale, consistency, accuracy), production recommendation

---

## Project Structure

```
ai_model_2_ai_product/Assignments/1/
├── plan.md                                # This file
├── assignment_01.ipynb                    # Main notebook (all tasks)
├── Assignment_01_product_dataset.xlsx     # Input dataset
├── assignment_01.xlsx                     # Output with evaluations
└── src/
    ├── config.py                          # API keys, model endpoints
    ├── rubric.py                          # Rubric definitions + pass/fail logic
    ├── generator.py                       # Generate descriptions via LLM API
    └── judge.py                           # LLM-as-a-judge with Pydantic schema
```

## Key Technical Decisions

1. **OpenAI API** - using OPENAI_API_KEY from project root `.env` file
2. **Pydantic** for structured output (required by assignment)
3. **Jupyter notebook** as main driver for visibility/documentation, with reusable modules in `src/`
4. **pandas + openpyxl** for Excel I/O
