# CC10x Orchestration (Always On)

IMPORTANT: ALWAYS invoke cc10x-router on ANY development task. First action, no exceptions.
IMPORTANT: Explore project first, then invoke the router.
IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for orchestration decisions.
IMPORTANT: Never bypass the router. It is the system.
IMPORTANT: NEVER use Edit, Write, or Bash (for code changes) without first invoking cc10x-router.

**Skip CC10x ONLY when:**
- User EXPLICITLY says "don't use cc10x", "without cc10x", or "skip cc10x"
- No interpretation. No guessing. Only these exact opt-out phrases.

[CC10x]|entry: cc10x:cc10x-router

---

## Complementary Skills (Work Together with CC10x)

**Skills are additive, not exclusive.** CC10x provides orchestration. Domain skills provide expertise. Both work together.

**GATE:** Before writing code, check if task matches a skill below. If match, invoke it via `Skill(skill="...")`.

| When task involves... | Invoke |
|-----------------------|--------|
| Explaining how code works, teaching codebase | `explain-code` |
| Interactive HTML playgrounds, visual explorers | `playground:playground` |
| Claude Code setup, automation recommendations | `claude-code-setup:claude-automation-recommender` |