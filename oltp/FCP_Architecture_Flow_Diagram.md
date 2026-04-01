# FCP Architecture — Component Flow Diagram with Estimated Latency

## Flow 1: Real-Time Fraud Scoring (Synchronous — Target <50ms)

```
                                        END-TO-END TARGET: <50ms
                                        REALISTIC P99: 70-150ms

  Customer                 Unified API              Model Serving           Lakebase Silver         THE BRAIN              Feature World
  Transaction              Gateway                  Endpoint (MSE)          (Feature Lookup)        (Risk Mitigation)      (Write-back)
     |                        |                        |                        |                       |                      |
     |--- HTTP POST --------->|  ~2-5ms                |                        |                       |                      |
     |                        |  (TLS + auth +         |                        |                       |                      |
     |                        |   normalize + route)   |                        |                       |                      |
     |                        |                        |                        |                       |                      |
     |                        |--- REST/gRPC --------->|  ~3-8ms                |                       |                      |
     |                        |                        |  (network + routing    |                       |                      |
     |                        |                        |   to provisioned MSE)  |                       |                      |
     |                        |                        |                        |                       |                      |
     |                        |                        |--- SQL/JDBC ---------->|  ~2-5ms P50           |                      |
     |                        |                        |   Feature lookup       |  ~15-40ms P99         |                      |
     |                        |                        |   (party risk score,   |  (pg_prewarm warm)    |                      |
     |                        |                        |    device fingerprint, |                       |                      |
     |                        |                        |    auth signals,       |  COLD START WARNING:  |                      |
     |                        |                        |    velocity counts)    |  ~50-100ms P99        |                      |
     |                        |                        |                        |  (after scale-to-zero |                      |
     |                        |                        |<--- feature vector ----|   or compute restart) |                      |
     |                        |                        |                        |                       |                      |
     |                        |                        |  ML INFERENCE          |                       |                      |
     |                        |                        |  ~5-20ms P50           |                       |                      |
     |                        |                        |  ~30-80ms P99          |                       |                      |
     |                        |                        |  (XGBoost/LightGBM     |                       |                      |
     |                        |                        |   fraud model)         |                       |                      |
     |                        |                        |                        |                       |                      |
     |                        |                        |--- fraud score ------->|                       |                      |
     |                        |                        |   + decision request   |--- decision ---------->                      |
     |                        |                        |                        |   ~3-10ms             |                      |
     |                        |                        |                        |   (BLOCK/HOLD/ALLOW   |                      |
     |                        |                        |                        |    + write audit log) |                      |
     |                        |                        |                        |                       |                      |
     |<--- ALLOW/DENY --------|<--- response ----------|                        |                       |--- async signals --->|
     |                        |                        |                        |                       |  (Mambu, PSP, INC,   |
     |                        |                        |                        |                       |   Darwinium, Flowable)|
     |                        |                        |                        |                       |  ~50-500ms (async,   |
                                                                                                       |   not on hot path)   |

  LATENCY BUDGET SUMMARY (P50 → P99):
  ┌──────────────────────────────────┬────────────┬─────────────┐
  │ Component                        │ P50        │ P99         │
  ├──────────────────────────────────┼────────────┼─────────────┤
  │ API Gateway (TLS + auth + route) │ 2-5 ms     │ 5-15 ms     │
  │ Network to MSE                   │ 3-8 ms     │ 8-20 ms     │
  │ Lakebase feature lookup (warm)   │ 2-5 ms     │ 15-40 ms    │
  │ ML model inference               │ 5-20 ms    │ 30-80 ms    │
  │ Brain decision + audit write     │ 3-10 ms    │ 10-30 ms    │
  ├──────────────────────────────────┼────────────┼─────────────┤
  │ TOTAL                            │ 15-48 ms   │ 68-185 ms   │
  └──────────────────────────────────┴────────────┴─────────────┘

  VERDICT: P50 can hit <50ms. P99 CANNOT hit <50ms — expect 70-150ms.
  The Lakebase feature lookup and ML inference are the two bottlenecks.
```

---

## Flow 2: AML Transaction Monitoring (Batch — Overnight/Hourly)

```
  Lakebase               Databricks               Flowable                 Lakebase Gold           Case Mgmt
  Silver                 Spark Jobs               DMN + BPMN               (Delta Lake)            (Superblocks)
     |                        |                        |                        |                       |
     |--- Spark read -------->|  ~1-5 sec              |                        |                       |
     |   (full Silver scan,   |  (streaming startup    |                        |                       |
     |    Delta CDF, or       |   + data read)         |                        |                       |
     |    scheduled batch)    |                        |                        |                       |
     |                        |                        |                        |                       |
     |                        |  TM FEATURE COMPUTE    |                        |                       |
     |                        |  ~5-30 min             |                        |                       |
     |                        |  (aggregate txns per   |                        |                       |
     |                        |   party: velocity,     |                        |                       |
     |                        |   structuring patterns,|                        |                       |
     |                        |   counterparty chains) |                        |                       |
     |                        |                        |                        |                       |
     |                        |  TM TYPOLOGY RULES     |                        |                       |
     |                        |  ~10-60 min            |                        |                       |
     |                        |  (Spark notebooks:     |                        |                       |
     |                        |   threshold rules,     |                        |                       |
     |                        |   ML anomaly scoring)  |                        |                       |
     |                        |                        |                        |                       |
     |                        |--- alert candidates -->|  ~5-15 ms/case         |                       |
     |                        |                        |  (DMN rule eval:       |                       |
     |                        |                        |   1-3 ms in-memory)    |                       |
     |                        |                        |                        |                       |
     |                        |                        |  BPMN case creation    |                       |
     |                        |                        |  ~10-30 ms/case        |                       |
     |                        |                        |  (create process +     |                       |
     |                        |                        |   persist state +      |                       |
     |                        |                        |   assign analyst)      |                       |
     |                        |                        |                        |                       |
     |                        |--- write Gold -------->|                        |--- audit + STR/SAR -->|
     |                        |   ~1-5 sec             |  ~2-10 sec             |                       |
     |                        |   (Delta write +       |  (Delta merge +        |   Analyst reviews     |
     |                        |    OPTIMIZE +          |   Z-order +            |   in case UI          |
     |                        |    Z-order)            |   time-travel          |   ~minutes to hours   |
     |                        |                        |   retention set)       |                       |

  LATENCY BUDGET SUMMARY:
  ┌──────────────────────────────────┬────────────────────┐
  │ Component                        │ Duration           │
  ├──────────────────────────────────┼────────────────────┤
  │ Silver → Spark read              │ 1-5 sec            │
  │ TM feature aggregation           │ 5-30 min           │
  │ Typology rules (Spark notebooks) │ 10-60 min          │
  │ Flowable DMN evaluation          │ 1-3 ms per rule    │
  │ BPMN case creation               │ 10-30 ms per case  │
  │ Gold write (Delta)               │ 1-5 sec            │
  ├──────────────────────────────────┼────────────────────┤
  │ TOTAL END-TO-END                 │ 20 min - 2 hours   │
  └──────────────────────────────────┴────────────────────┘

  VERDICT: Batch is fine. Databricks handles this well.
  Risk: Silver → Gold ETL window creates a staleness gap in regulatory views.
```

---

## Flow 3: CDD / Onboarding (Near Real-Time)

```
  Customer              INC                   Lakebase              Zingg.ai              Flowable             Lakebase
  Onboarding            (Orchestrator)        Bronze                (Entity Res)          CDD BPMN             Silver
     |                        |                    |                      |                     |                   |
     |--- apply ------------->|  ~100-500ms         |                      |                     |                   |
     |   (FaceTec liveness    |  (IDV pipeline:     |                      |                     |                   |
     |    + Daon doc verify   |   FaceTec + Daon    |                      |                     |                   |
     |    + PhilSys/DHA)      |   + govt ID check)  |                      |                     |                   |
     |                        |                     |                      |                     |                   |
     |                        |--- raw event ------->|  ~3-8ms             |                     |                   |
     |                        |   (write Bronze)     |  (Lakebase insert)  |                     |                   |
     |                        |                      |                     |                     |                   |
     |                        |                      |                     |                     |                   |
     |                        |         ENTITY RESOLUTION GAP             |                     |                   |
     |                        |         ================================  |                     |                   |
     |                        |         Zingg.ai is BATCH ONLY            |                     |                   |
     |                        |         ~15-60 min for 1M records         |                     |                   |
     |                        |         New customer has NO resolved      |                     |                   |
     |                        |         party_id until next batch run     |                     |                   |
     |                        |         ================================  |                     |                   |
     |                        |                      |                     |                     |                   |
     |                        |                      |--- batch job ------->  ~15-60 min        |                   |
     |                        |                      |   (Spark cluster     |  (Fellegi-Sunter   |                   |
     |                        |                      |    scheduled run)    |   match + merge)   |                   |
     |                        |                      |                     |                     |                   |
     |                        |                      |<--- party_id -------|                     |                   |
     |                        |                      |                     |                     |                   |
     |                        |--- CDD trigger ------>                     |--- start BPMN ----->  ~10-30ms         |
     |                        |                      |                     |  (CDD process:      |                   |
     |                        |                      |                     |   HRC/IVR/PRE       |                   |
     |                        |                      |                     |   risk scoring)     |                   |
     |                        |                      |                     |                     |                   |
     |                        |                      |                     |  DMN CRR scoring    |                   |
     |                        |                      |                     |  ~1-3ms             |--- write Silver -->|
     |                        |                      |                     |  (risk weights      |  ~3-8ms            |
     |                        |                      |                     |   + jurisdiction    |  (CDD result +     |
     |                        |                      |                     |   rules)            |   risk tier)       |
     |                        |                      |                     |                     |                   |
     |                        |                      |  SCREENING          |                     |                   |
     |                        |                      |  ~50-200ms          |                     |                   |
     |                        |                      |  (LSEG Refinitiv    |                     |                   |
     |                        |                      |   PEP/Sanctions     |                     |                   |
     |                        |                      |   + pg_trgm fuzzy)  |                     |                   |

  LATENCY BUDGET SUMMARY:
  ┌──────────────────────────────────┬────────────────────┐
  │ Component                        │ Duration           │
  ├──────────────────────────────────┼────────────────────┤
  │ IDV (FaceTec + Daon + Govt)      │ 100-500 ms         │
  │ Bronze write                     │ 3-8 ms             │
  │ Entity resolution (Zingg batch)  │ 15-60 MIN (!)      │
  │ Screening (LSEG + pg_trgm)      │ 50-200 ms          │
  │ Flowable CDD BPMN start         │ 10-30 ms           │
  │ DMN CRR scoring                  │ 1-3 ms             │
  │ Silver write                     │ 3-8 ms             │
  ├──────────────────────────────────┼────────────────────┤
  │ TOTAL (excl. entity res)         │ ~200ms - 1 sec     │
  │ TOTAL (with entity res batch)    │ 15 min - 1 hour    │
  └──────────────────────────────────┴────────────────────┘

  VERDICT: The Zingg.ai batch gap is a CRITICAL issue for onboarding.
  Customer cannot have a resolved party_id in real-time.
  Need: deterministic pre-match at onboarding → Zingg reconciles in batch.
```

---

## Flow 4: PuppyGraph Investigation (Analyst-Driven, Interactive)

```
  Analyst                Superblocks           PuppyGraph              Lakebase Silver
  (Case UI)              (or Databricks App)   (Graph Engine)          (Source Tables)
     |                        |                     |                       |
     |--- open case --------->|  ~200-500ms          |                       |
     |   (load party profile  |  (page render +      |                       |
     |    + case details)     |   Lakebase query)    |                       |
     |                        |                      |                       |
     |--- "show network" ---->|                      |                       |
     |                        |--- Gremlin/Cypher -->|  ~10-30ms P50         |
     |                        |   (1-hop: accounts,  |  ~50-100ms P99        |
     |                        |    devices, addrs)   |  (cached topology)    |
     |                        |                      |                       |
     |                        |                      |--- JDBC queries ----->|
     |                        |                      |   (vertex/edge        |  ~2-5ms per query
     |                        |                      |    properties)        |  (warm cache)
     |                        |                      |                       |
     |                        |--- "expand 2nd hop"->|  ~30-150ms P50        |
     |                        |   (counterparties,   |  ~200-500ms P99       |
     |                        |    shared devices,   |  (multiple JDBC       |
     |                        |    sanctioned links) |   round-trips)        |
     |                        |                      |                       |
     |                        |--- "fraud ring" ---->|  ~100-500ms P50       |
     |                        |   (centrality algo,  |  ~500ms-2sec P99      |
     |                        |    community detect) |  (graph algorithm     |
     |                        |                      |   on cached topology) |
     |                        |                      |                       |
     |<--- graph viz ---------|<--- results ---------|                       |

  LATENCY BUDGET SUMMARY:
  ┌──────────────────────────────────┬────────────┬─────────────┐
  │ Query Type                       │ P50        │ P99         │
  ├──────────────────────────────────┼────────────┼─────────────┤
  │ 1-hop traversal                  │ 10-30 ms   │ 50-100 ms   │
  │ 2-3 hop traversal                │ 30-150 ms  │ 200-500 ms  │
  │ Graph algorithm (centrality)     │ 100-500 ms │ 0.5-2 sec   │
  │ Full case page load              │ 200-500 ms │ 1-3 sec     │
  └──────────────────────────────────┴────────────┴─────────────┘

  VERDICT: Acceptable for analyst-facing interactive use.
  Risk: At 25M customers with N-year history, graph size may push
  algorithms into multi-second territory. Need to validate with real data.
```

---

## Flow 5: Silver → Gold ETL (The Hidden Data Movement)

```
  Lakebase Silver         Databricks Jobs          Delta Lake Gold          Downstream
  (PostgreSQL)            (Spark Batch)            (Analytics/Regulatory)   (AI/BI, Reporting)
     |                        |                        |                       |
     |--- JDBC read --------->|  ~5-30 sec              |                       |
     |   (full table or CDC   |  (connect + scan        |                       |
     |    from Silver tables) |   Silver tables)        |                       |
     |                        |                        |                       |
     |                        |  TRANSFORM              |                       |
     |                        |  ~5-30 min              |                       |
     |                        |  (aggregate, join,      |                       |
     |                        |   compute risk scores,  |                       |
     |                        |   build ML features,    |                       |
     |                        |   format goAML/STR)     |                       |
     |                        |                        |                       |
     |                        |--- Delta MERGE -------->|  ~30 sec - 5 min     |
     |                        |   (write Gold tables,   |  (merge + OPTIMIZE   |
     |                        |    OPTIMIZE, Z-order)   |   + Z-order)         |
     |                        |                        |                       |
     |                        |                        |--- refresh views ---->|
     |                        |                        |   ~1-10 sec           |
     |                        |                        |   (materialized       |
     |                        |                        |    views, dashboards) |

  LATENCY BUDGET SUMMARY:
  ┌──────────────────────────────────┬────────────────────┐
  │ Component                        │ Duration           │
  ├──────────────────────────────────┼────────────────────┤
  │ Silver JDBC read                 │ 5-30 sec           │
  │ Spark transformation             │ 5-30 min           │
  │ Gold Delta write + optimize      │ 30 sec - 5 min     │
  │ View refresh                     │ 1-10 sec           │
  ├──────────────────────────────────┼────────────────────┤
  │ TOTAL                            │ 10 min - 1 hour    │
  │ STALENESS GAP                    │ = scheduled freq   │
  └──────────────────────────────────┴────────────────────┘

  VERDICT: This IS ETL. It contradicts the "no data movement" claim.
  The Gold layer is always stale by the ETL schedule interval.
  Regulatory reports query Gold, so they reflect data from last ETL run.

  MITIGATION OPTIONS:
  - Lakeflow DLT with streaming (near-real-time Silver → Gold)
  - Synced Tables (continuous mode via CDF) — still evaluating maturity
  - Accept staleness for batch reporting (most regulators do)
```

---

## Master Component Latency Reference Table

```
  ┌─────────────────────────────────────┬────────────┬─────────────┬───────────────────────────────────┐
  │ Component                           │ P50        │ P99         │ Notes                             │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ LAKEBASE                            │            │             │                                   │
  │  Read (warm, pg_prewarm)            │ 2-5 ms     │ 15-40 ms   │ Buffer cache hit                  │
  │  Read (cold, after restart)         │ 8-15 ms    │ 50-100 ms  │ Pageserver fetch                  │
  │  Write (single row)                 │ 3-8 ms     │ 15-40 ms   │ WAL to safekeepers                │
  │  Connection overhead                │ 1-3 ms     │ 5-10 ms    │ Per new connection                │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ MODEL SERVING (MLflow MSE)          │            │             │                                   │
  │  XGBoost/LightGBM inference         │ 5-20 ms    │ 30-80 ms   │ Provisioned, non-serverless       │
  │  Feature lookup (from Lakebase)     │ 2-5 ms     │ 15-40 ms   │ Included in fraud path            │
  │  Cold start (scale from zero)       │ 30-120 sec │ N/A        │ MUST disable scale-to-zero        │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ FLOWABLE                            │            │             │                                   │
  │  DMN table evaluation               │ 1-3 ms     │ 5-15 ms    │ In-memory, simple rules           │
  │  BPMN process start                 │ 10-30 ms   │ 50-150 ms  │ Includes DB persistence           │
  │  User task completion               │ 3-10 ms    │ 20-50 ms   │ State write to Lakebase           │
  │  Full process (10 auto tasks)       │ 20-80 ms   │ 100-300 ms │ Multiple DB round-trips           │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ PUPPYGRAPH                          │            │             │                                   │
  │  1-hop traversal                    │ 10-30 ms   │ 50-100 ms  │ Cached topology + JDBC            │
  │  2-3 hop traversal                  │ 30-150 ms  │ 200-500 ms │ Multiple JDBC round-trips         │
  │  Graph algorithm (centrality)       │ 100-500 ms │ 0.5-2 sec  │ Depends on subgraph size          │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ ZINGG.AI (Entity Resolution)        │            │             │                                   │
  │  100K records                       │ 2-10 min   │ N/A        │ Spark batch job                   │
  │  1M records                         │ 15-60 min  │ N/A        │ Depends on cluster size           │
  │  10M records                        │ 2-8 hours  │ N/A        │ Blocking/indexing critical         │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ SPARK STRUCTURED STREAMING          │            │             │                                   │
  │  Delta-to-Delta (micro-batch)       │ 1-2 sec    │ 5-15 sec   │ Without Kafka                     │
  │  Auto Loader (cloud files)          │ 5-30 sec   │ 30-120 sec │ File notification delay           │
  ├─────────────────────────────────────┼────────────┼─────────────┼───────────────────────────────────┤
  │ NETWORK / INFRASTRUCTURE            │            │             │                                   │
  │  API Gateway (TLS + auth + route)   │ 2-5 ms     │ 5-15 ms    │ Standard cloud API GW             │
  │  Intra-Databricks network hop       │ 1-3 ms     │ 3-8 ms     │ Between Databricks services       │
  │  External API call (Mambu, PSP)     │ 50-200 ms  │ 200-1 sec  │ Core banking write-back           │
  │  LSEG Refinitiv screening           │ 50-200 ms  │ 200-500 ms │ External sanctions API            │
  └─────────────────────────────────────┴────────────┴─────────────┴───────────────────────────────────┘

  SOURCES:
  - Lakebase: Extrapolated from Neon Postgres published benchmarks + Databricks network overhead
  - MSE: Databricks documentation + community benchmarks for XGBoost serving
  - Flowable: Flowable team benchmarks (Filip Hrisafov), Flowable 6 performance blog
  - PuppyGraph: PuppyGraph documentation + JDBC overhead estimates
  - Zingg.ai: Zingg GitHub repo, Sonal Goyal conference talks, Databricks community posts
  - Streaming: Databricks "Project Lightspeed" blog, Structured Streaming documentation

  NOTE: All Lakebase numbers are ESTIMATES based on Neon architecture.
  No published Lakebase-specific benchmarks exist as of March 2026.
  MUST validate with actual PoC benchmarking.
```

---

## Architecture Risk Heat Map

```
  ┌─────────────────────────────────────────────┬──────────┬────────────────────────────────────────┐
  │ Risk                                        │ Severity │ Mitigation                             │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Fraud path P99 > 50ms                       │ HIGH     │ Add Redis cache layer OR accept        │
  │                                             │          │ 100ms P99 target                       │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ The Brain runtime undefined                 │ HIGH     │ Define: is it a Spark job, a service,  │
  │                                             │          │ or stored procedures?                  │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Flowable on Lakebase (Neon) untested        │ HIGH     │ PoC Flowable on Lakebase under load    │
  │                                             │          │ before committing                      │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Zingg.ai batch gap during onboarding        │ HIGH     │ Add deterministic pre-match at         │
  │                                             │          │ onboarding, Zingg reconciles in batch  │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Silver → Gold is ETL (contradicts           │ MEDIUM   │ Use Lakeflow DLT streaming or accept   │
  │ shift-left "no data movement" claim)        │          │ staleness for batch reporting           │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Lakebase compute restart loses cache        │ MEDIUM   │ Disable scale-to-zero on hot path +    │
  │                                             │          │ pg_prewarm on startup + graceful degrad │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ PuppyGraph at 25M customers + N-year hist   │ MEDIUM   │ Validate graph size; may need graph    │
  │                                             │          │ partitioning or time-windowed subgraphs │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ No DR / cross-region failover plan          │ MEDIUM   │ Design before production go-live       │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Unity Catalog ABAC still in Preview         │ LOW      │ Use row-level security (GA) as         │
  │                                             │          │ fallback for dual-jurisdiction          │
  ├─────────────────────────────────────────────┼──────────┼────────────────────────────────────────┤
  │ Multiple Lakebase projects needed           │ LOW      │ Separate hot-path / operational /      │
  │ (workload isolation)                        │          │ ingest — increases cost but necessary   │
  └─────────────────────────────────────────────┴──────────┴────────────────────────────────────────┘
```
