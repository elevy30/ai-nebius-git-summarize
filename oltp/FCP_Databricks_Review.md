# Review: Databricks in the FCP Architecture

## The Core Tension

The FCP deck makes a bold claim: **everything runs on Databricks**. That's the shift-left pitch. But Databricks is fundamentally an **analytics and ML platform** that recently added OLTP capabilities (Lakebase). The FCP is asking it to also be a **real-time transaction processing system, a workflow engine backend, and an application database** — simultaneously.

Below is a breakdown of where Databricks is the right tool, where it's being stretched, and where it's the wrong tool.

---

## Where Databricks is GENUINELY the Best Choice

### 1. The Gold Layer — Analytics, Regulatory Reporting, Audit

This is Databricks' home turf. Delta Lake with time-travel for 7-year regulatory archives, Z-order for fast query on BSP/SARB examination queries, Unity Catalog for governance — there is no better platform for this. No debate.

- STR/CTR canonical views: SQL on Delta Lake Gold — perfect
- goAML reporting dataset: Spark batch job producing regulatory XML — perfect
- MIS / Board-level dashboards: AI/BI Dashboards on Gold — perfect
- Rule replay against historical data: Delta time-travel + notebooks — perfect

**Confidence: 10/10. This is what Databricks was built for.**

### 2. ML Model Training and Batch Scoring

- Fraud model training on historical transaction data — MLflow + Spark, excellent
- CRR (Customer Risk Rating) batch scoring — Spark notebook, excellent
- TM typology feature engineering (aggregates, velocity, structuring detection) — Spark batch, excellent
- Champion/challenger model comparison — MLflow experiment tracking, excellent

**Confidence: 10/10.**

### 3. AML Transaction Monitoring (Batch)

Overnight TM batch is a perfect Databricks workload:
- Read Silver tables → compute aggregates → apply typology rules → generate alert candidates
- This is just Spark SQL + notebooks on a schedule
- Databricks Jobs handles orchestration, retry, SLA monitoring
- Output goes to Gold (Delta) and triggers Flowable cases via API

**Confidence: 9/10. Only risk is orchestration complexity if there are 50+ interdependent jobs.**

### 4. Entity Resolution (Zingg.ai)

Zingg.ai runs natively on Spark. Databricks is the right platform. The issue isn't Databricks — it's that Zingg is batch-only while onboarding needs real-time dedup. That's a Zingg limitation, not a Databricks one.

**Confidence: 8/10 for batch. 0/10 for real-time onboarding dedup.**

### 5. Data Ingestion (Bronze)

Lakeflow Connect for ingesting from core banking (Mambu), LSEG Refinitiv, Darwinium, PSP — this is what Lakeflow was built for. Auto Loader for file-based sources, structured streaming for event sources.

**Confidence: 8/10. Depends on connector maturity for specific FinCrime sources like LSEG.**

---

## Where Databricks is Being STRETCHED

### 6. Lakebase as the Feature Store for Real-Time Fraud

The architecture uses Lakebase Silver as the feature store — party risk scores, device fingerprints, velocity counts — read by MSE during real-time scoring.

This *can work*, but it's not what Lakebase was designed for. Lakebase is a Postgres database for application state. Using it as a low-latency feature store means:
- You're competing with Databricks' own **Feature Store** (which uses Delta tables, not Lakebase)
- You need `pg_prewarm` + provisioned compute + disabled scale-to-zero — essentially fighting Lakebase's serverless design
- You're paying for always-on Postgres compute when Databricks Feature Store with online tables (backed by DynamoDB/Cosmos) would give you guaranteed sub-5ms reads

**My take:** Use **Databricks Online Feature Store** (online tables backed by a key-value store) for the fraud hot path instead of raw Lakebase SQL queries. The features are still computed in Databricks, governed by Unity Catalog, but served from an optimized read path. This is how Databricks themselves recommend real-time feature serving.

**Confidence in current design: 5/10. Confidence with Online Feature Store: 8/10.**

### 7. Model Serving Endpoints for Real-Time Fraud

MSE for fraud scoring is reasonable — Databricks supports provisioned throughput for guaranteed latency. But the deck says "sub-10ms inference." That's only true for trivial models. A production fraud model with 50+ features, ensemble methods, and post-processing will be 15-40ms at P50.

More importantly: **who holds the HTTP connection?** The transaction comes in from the mobile app, needs a synchronous ALLOW/DENY response. The flow is:

```
Mobile → API Gateway → ??? → MSE → Lakebase → Brain → ??? → API Gateway → Mobile
```

Databricks MSE is a model inference endpoint, not a request orchestrator. Something needs to:
1. Receive the transaction
2. Call Lakebase for features
3. Call MSE for scoring
4. Call the Brain for decision
5. Return the response

That "something" is NOT a Databricks component. It's a lightweight **orchestration microservice** (Python/Go) running outside Databricks. The deck doesn't acknowledge this.

**Confidence: 6/10. MSE for inference is fine. The orchestration gap is the problem.**

### 8. "The Brain" on Databricks

This is the weakest part of the architecture. The Brain is described as running on "Databricks, non-serverless, provisioned compute." But what runtime?

- **Databricks notebook?** — Notebooks are for batch/interactive work, not for receiving real-time HTTP requests and responding in <50ms
- **Long-running Spark job?** — Spark has a ~50ms overhead just for task scheduling. Not suitable for synchronous request/response
- **Python service on a Databricks cluster?** — You *can* run a Flask/FastAPI app on a Databricks cluster, but that's an anti-pattern. You're paying for Spark infrastructure to run a simple Python service

**My take:** The Brain should be a **lightweight stateless service** (Python FastAPI, deployed on Kubernetes or Databricks Apps) that:
- Receives decisions from MSE and Flowable
- Applies simple rule logic (if score > threshold → BLOCK)
- Writes to Lakebase (audit trail)
- Calls external systems (Mambu, PSP) for write-back

This is a microservice — and that's OK. Not everything should be a Spark job. The shift-left principle still holds: **the data and ML stay in Databricks**, but the thin orchestration layer doesn't need to.

**Confidence in current design: 3/10. The Brain as described cannot work on Databricks.**

---

## Where Databricks is the WRONG Tool

### 9. Flowable's Backend Database

The deck puts Flowable on Lakebase as its Postgres backend. Flowable writes heavily — every BPMN state transition, every task assignment, every timer event writes to the database. Flowable expects standard Postgres behavior:
- Fast WAL commits (Lakebase WAL goes to remote safekeepers — slower)
- Stable connections (Lakebase connections can reset on autoscale events)
- Logical replication (not supported on Lakebase)

**My take:** Run Flowable on **standard managed Postgres** (RDS, Cloud SQL, or Azure Database for Postgres). Flowable reads FCP data FROM Lakebase via JDBC, but its own internal state lives on a standard Postgres. This is a clean separation — Flowable is a workflow engine, not a Databricks workload.

**Confidence in current design: 2/10. High risk of Flowable instability on Lakebase.**

### 10. Real-Time Event Routing / Message Bus

The architecture has no message bus. Transactions arrive synchronously and need synchronous responses. But there's also a need for:
- Async signals from the Brain to external systems (Mambu, PSP, INC)
- Event-driven triggers (new screening hit → re-evaluate all matching customers)
- Flowable process triggers from Databricks batch jobs

Databricks doesn't have a native event bus. The deck mentions "Zerobus" (exploring) but that's very early. In practice you need **Kafka, EventBridge, or a similar message broker** for:
- Brain → Feature World async signals
- Batch job completion → Flowable case creation
- Screening list update → re-screening trigger

**Confidence that Databricks alone can handle this: 2/10. Need an event bus.**

---

## Recommended Architecture Adjustment

```
KEEP ON DATABRICKS (its strengths):
├── Bronze → Silver → Gold medallion (Lakebase + Delta Lake)
├── All ML training + batch scoring (MLflow + Spark)
├── AML Transaction Monitoring batch (Spark Jobs)
├── Entity Resolution (Zingg.ai on Spark)
├── CRR scoring batch (Spark notebooks)
├── Feature engineering + feature store (Online Feature Store for serving)
├── Gold regulatory reporting + audit (Delta Lake)
├── Unity Catalog governance (everything)
└── AI/BI dashboards

MOVE OFF DATABRICKS (not its strengths):
├── Flowable backend DB → Standard managed Postgres (RDS/Cloud SQL)
├── The Brain → Lightweight Python service (K8s or Databricks Apps)
├── Fraud orchestration → Thin API service that calls MSE + Feature Store
├── Event routing → Kafka or EventBridge (Brain → Feature World signals)
└── Real-time feature serving → Databricks Online Tables (not raw Lakebase SQL)
```

## The Bottom Line

Databricks should be the **data platform, ML platform, and governance platform** — that's 70-80% of the FCP. But it should NOT be the **application runtime** for real-time orchestration, workflow engine hosting, or event routing. Trying to force those onto Databricks is where this architecture will break.

The shift-left principle still holds: all data, all ML, all rules-as-data, all governance live in Databricks. But the thin orchestration layer (The Brain, event routing, Flowable runtime) should run on purpose-built infrastructure that reads from and writes to Databricks.

This isn't a compromise — it's the correct architecture. Even Databricks' own reference architectures for real-time applications show a lightweight serving layer in front of the platform.
