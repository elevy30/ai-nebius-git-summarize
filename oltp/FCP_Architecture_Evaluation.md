# Architecture Evaluation — Can This Run End-to-End on Databricks?

## What Works Well

The shift-left principle is sound. Keeping logic at the data layer eliminates the #1 problem in FinCrime platforms: data movement creating inconsistency and latency. The medallion architecture (Bronze→Silver→Gold) is a proven pattern. Unity Catalog as the single governance plane is the right call for dual-jurisdiction (PH/SA).

## Critical Gaps & Risks

### 1. The Sub-50ms Fraud Path — Highest Risk Item

**The claim:** Transaction → API Gateway → Model Serving Endpoint → Lakebase Silver (feature lookup) → Brain → Response in <50ms.

**The reality problem:** This chain has **at minimum 4 network hops**. Let's break it down:
- API Gateway → MSE: ~5-10ms (network + cold routing)
- MSE → Lakebase Silver (feature lookup via SQL): **This is the bottleneck.** Lakebase is Postgres-over-Neon. Even with `pg_prewarm`, a SQL query to Lakebase involves: TCP connection → query parse → buffer lookup → return. Realistic P50 is 3-8ms, but **P99 under load could be 20-40ms** just for this hop.
- MSE inference: ~2-5ms (provisioned)
- MSE → Brain → response: ~5-10ms

**Total realistic P99: 40-80ms**, not sub-50ms. The doc says sub-10ms for MSE inference, which is achievable, but the **feature lookup from Lakebase is not sub-10ms at P99** — especially under concurrent fraud scoring load.

**Question for the team:** Has anyone benchmarked Lakebase read latency at P99 under concurrent load? The `pg_prewarm` strategy helps P50 but doesn't guarantee P99. Redis/Memcached as a feature cache between Lakebase Silver and MSE would be more realistic for sub-50ms — but that breaks the "no data movement" principle.

### 2. Lakebase as Both OLTP and Feature Store — Architecture Tension

The doc uses Lakebase for:
- Bronze raw ingest (write-heavy)
- Silver operational tables (read/write)
- Feature store for real-time fraud scoring (read-heavy, latency-critical)
- Flowable's backend database
- PuppyGraph source

**Risk:** These are fundamentally different workload profiles. Even with read replicas, a single Lakebase project serving all these purposes will have contention issues. Lakebase autoscaling helps, but it's **reactive** — a burst of TM batch writes to Silver can degrade the fraud feature lookup P99 at the worst possible time.

**Recommendation:** At minimum, separate Lakebase projects for:
- **Hot path** (fraud features, provisioned, no scale-to-zero)
- **Operational** (Flowable backend, case mgmt, Silver tables)
- **Ingest** (Bronze writes)

### 3. "The Brain" — Insufficiently Defined

The Brain is described as the single decisioning core, but the doc doesn't specify:
- **What is it actually?** A Databricks notebook? A long-running Spark job? A Python service on a provisioned cluster? A Lakebase stored procedure?
- **How does it receive real-time triggers?** The diagram shows MSE → Brain, but Databricks doesn't have a native event-driven invocation mechanism for notebooks.
- **How does it write back to Mambu/PSP/INC?** These are synchronous write-backs to external core banking systems. If the Brain is a Spark job, it can't respond in-line to a real-time fraud request.

**This is the biggest architectural ambiguity in the entire deck.**

### 4. Flowable ↔ Lakebase Integration — Untested at Scale

The doc assumes Flowable DMN/BPMN/CMMN runs directly on Lakebase as its database. Flowable is traditionally deployed on standard PostgreSQL. Lakebase is Neon-based with:
- Ephemeral compute (cache lost on restart)
- Higher write latency than standard Postgres (WAL goes to safekeepers, not local disk)
- No support for some Postgres features (logical replication, custom C extensions)

**Risk:** Flowable's internal schema is write-heavy (process state, task tables, history). Flowable at scale on Neon-based Postgres is **completely unproven territory**. A single slow WAL flush could stall a BPMN process execution.

**Question for Databricks:** Has anyone run Flowable (or any BPMN engine) on Lakebase in production?

### 5. PuppyGraph Zero-Copy — Needs Validation

The doc says PuppyGraph reads Lakebase tables as graph vertices/edges with "zero-copy." PuppyGraph can read from JDBC sources, but:
- "Zero-copy" on Lakebase means PuppyGraph issues SQL queries — it's not reading memory pages directly
- Graph traversals (2nd/3rd degree for sanctions networks) generate **many sequential queries** — each hop is a round-trip
- At 25M customers with N-year history, the graph could have billions of edges

**Question:** What is PuppyGraph's actual query pattern against Lakebase? Is it caching graph topology in its own memory, or is every traversal hitting Postgres?

### 6. Zingg.ai Entity Resolution — Batch-Only

Zingg.ai runs as Spark batch jobs. The doc says entity resolution happens at Silver. But:
- **Onboarding is real-time** — a new customer needs a `party_id` before CDD can start
- If Zingg.ai is batch (hourly/daily), there's a window where a new customer exists without deduplication
- During that window, sanctions screening runs against an unresolved entity — potentially a false negative

**Question:** What is the entity resolution latency for onboarding? Is there a real-time dedup path, or is batch acceptable?

### 7. Dual Jurisdiction Data Residency — Not Addressed

The doc mentions PH (BSP/AMLC) and SA (SARB/FICA) and ~25M customers, but doesn't explain:
- Where does data physically reside? One Databricks workspace or two?
- Can PH customer data be processed in SA compute, or is there a data residency constraint?
- Unity Catalog ABAC is "in Preview" — is Preview acceptable for a regulated FinCrime platform?

### 8. Gold Layer — Delta Lake vs Lakebase Confusion

The doc says Bronze/Silver are PostgreSQL in Lakebase, and Gold is Delta Lake. But:
- How does data move from Lakebase Silver (Postgres) to Delta Lake Gold? That's ETL — the very thing shift-left is supposed to eliminate.
- Who runs this ETL? Databricks Jobs? On what schedule?
- During the ETL window, Gold is stale — meaning regulatory reporting views and the ML feature store are behind.

---

## Questions You Should Ask the Product Team / CTO

### Architecture Fundamentals

1. **"What exactly IS the Brain?"** — Is it a long-running service, a Spark job, a notebook triggered by events, or a set of Lakebase stored procedures? How does it receive real-time triggers from MSE and respond synchronously?

2. **"How does the real-time fraud path work synchronously end-to-end?"** — Draw the sequence diagram with actual millisecond budgets per hop. Where does the HTTP request enter, and where does the approve/deny response exit? Which component holds the connection open?

3. **"What happens when Lakebase compute restarts?"** — `pg_prewarm` reloads the cache, but during the reload window (could be seconds to minutes depending on table size), fraud scoring hits cold storage. What's the degradation plan?

4. **"How does data move from Silver (Lakebase/Postgres) to Gold (Delta Lake)?"** — If it's an ETL job, what's the freshness guarantee? This directly affects regulatory reporting accuracy.

### Latency & Scale

5. **"Has anyone benchmarked Lakebase read latency at P99 under concurrent write load?"** — Not P50, not in isolation. P99 while Bronze ingest, Flowable state writes, and fraud feature reads are all happening.

6. **"What is the target TPS for the fraud path?"** — 25M customers, but how many transactions per second? 100 TPS is very different from 10,000 TPS. The architecture may work at low TPS but fall apart at high TPS.

7. **"What is the failover story?"** — If Lakebase compute goes down, is there automatic failover? What's the RTO? For a fraud-blocking system, even 30 seconds of downtime means 30 seconds of unscored transactions.

### Component Choices

8. **"Why Flowable and not Databricks Workflows for orchestration?"** — Flowable adds significant complexity (another JVM runtime, its own database, its own scaling concerns). What does Flowable provide that Databricks Workflows + Delta Live Tables cannot?

9. **"Why PuppyGraph and not GraphFrames (native Spark)?"** — GraphFrames runs natively on Spark without another component. For batch graph analytics (fraud ring detection overnight), GraphFrames may be sufficient. Where specifically does PuppyGraph's real-time traversal add value that justifies the additional component?

10. **"Why Superblocks for case UI?"** — If Flowable Work already provides a case management UI, why add Superblocks? Two UX frameworks = two things to maintain.

11. **"What is the Zingg.ai real-time dedup story for onboarding?"** — If a customer applies and Zingg.ai runs in batch, how long until they have a resolved `party_id`? Is there an interim deterministic match for onboarding that Zingg.ai later reconciles?

### Regulatory & Governance

12. **"Is Unity Catalog ABAC (Preview) acceptable for a BSP/SARB-regulated platform?"** — Preview features can change or be deprecated. What's the fallback if ABAC doesn't GA in time?

13. **"Where does the 7-year audit trail physically live, and who owns the retention policy?"** — Delta Lake time-travel has a configurable retention. If someone runs `VACUUM` with a short retention, the audit trail is gone. What prevents this?

14. **"How do you demonstrate to BSP/SARB that a rule change didn't retroactively affect past decisions?"** — The doc mentions DMN versioning + Delta time-travel. But is there an actual tested procedure, or is this theoretical?

### Missing from the Deck

15. **"Where is the disaster recovery plan?"** — The entire platform is on Databricks. What happens if the Databricks region goes down? Is there a cross-region DR strategy?

16. **"Where is the data migration plan?"** — What data exists today, and how does it get into the medallion architecture? The deck describes the target state but not the path from current state.

17. **"What are the cost estimates?"** — Provisioned (non-serverless) Lakebase compute 24/7 for fraud, plus autoscaling for batch, plus MLflow MSE provisioned throughput, plus PuppyGraph, plus Flowable infrastructure. Has anyone modeled the monthly Databricks bill?

18. **"What is the team structure to build and operate this?"** — The deck mentions a 10-person team at Hafnia for a simpler use case. How many engineers does GoTyme need for FCP?

---

## Bottom Line Assessment

The architecture is **ambitious and conceptually sound** but has **three critical unknowns** that must be validated before committing:

1. **The real-time fraud path latency** — needs actual benchmarking, not theoretical estimates
2. **The Brain's runtime model** — this is architecturally undefined and is the central decision component
3. **Flowable on Lakebase at scale** — completely unproven combination

I'd recommend a **focused PoC** on the fraud path (items 1+2) before investing in the full platform build. If the sub-50ms target can't be met with Lakebase alone, the architecture needs a caching layer — which changes the entire shift-left premise.
