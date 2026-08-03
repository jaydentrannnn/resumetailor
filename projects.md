# Project Descriptions for Resume

Note: A few of these are team projects where you weren't the sole/majority committer (flagged below). Consider "contributed to" / "co-built" framing for those instead of full ownership language — worth a quick gut-check against your actual role before it goes on a resume.

---

## 1. Web Crawler — UCI ICS Information Retrieval Course Project

**Link:** https://github.com/AnthonyCoding373/spacetime-crawler4py

*(Team project — repo hosted under a teammate's account; you're credited as a contributor)*

Built a multithreaded web crawler for UCI's Information Retrieval course, designed to crawl and index the ics.uci.edu domain through a shared caching/politeness server (course infrastructure that fronts real requests so multiple students' crawlers can be graded without hammering live sites). The course provided the multithreaded frontier/worker skeleton — a `Frontier` that tracks to-be-downloaded URLs and marks completions for restartability, and `Worker` threads that pull a URL, download it through the cache, and hand the response to a custom scraper — and the team's job was to implement the actual scraping logic in `scraper.py`.

Implemented `extract_next_links`, which decodes the raw HTML response and regex-matches every `href`/`src` attribute (`(?:href|src)\s*=\s*["\']([^"\']+)["\']`) to pull outbound links directly from markup rather than relying on a full HTML parser. Implemented `is_valid`, a URL filter that: restricts crawling to hosts ending in `ics.uci.edu`; rejects non-http(s) schemes and malformed URLs; blocks a long list of non-textual file extensions (images, video, audio, CSS/JS, PDFs, Office docs, archives, binaries); strips out calendar/event pages and URLs with `date=`/`day` params (common infinite-crawl traps); and filters session-tracking query params (`sid=`, `session_id=`, `user=`) to avoid recrawling duplicate content under different session IDs. Crawler behavior (user agent, seed URL, cache host/port, politeness delay, thread count) was tunable via `config.ini`, with a `--restart` flag to wipe progress and recrawl from the seed URL.

**Tools/Tags:** Python, Multithreading, Web Crawling, Regex, URL Parsing/Filtering, HTTP, Information Retrieval

---

## 2. Fuzzy Vietnamese Street Name Search

**Link:** https://github.com/jaydentrannnn/Fuzzy-Vietnamese-Street-Search

Built a fuzzy-search engine to resolve messy, diacritic-heavy Vietnamese street name queries — including initials shorthand (e.g., "ntmk" for "Nguyễn Thị Minh Khai") and numeric/date-style names (e.g., "3/2" or "3t2" → "ba tháng hai") — to their canonical form in a reference list.

Designed a multi-step normalization pipeline (`utils.py`): lowercase the input, convert slash-separated number patterns to their spoken Vietnamese date form, convert standalone digits to Vietnamese number words, strip Vietnamese diacritics via Unidecode, remove common street-type prefixes (đường/duong, phố/pho, đại lộ/dai lo/đl, quốc lộ/quoc lo/ql, tỉnh lộ/tinh lo/tl, hẻm/hem), and collapse whitespace — producing a canonical form used for matching plus a derived initials key for shorthand lookup. Built the search flow (`rapid_fuzz_search.py`) as two stages: a single-token query first checks the initials index for exact shorthand matches; otherwise the query is normalized and matched against canonical forms using RapidFuzz's WRatio scorer (score cutoff 80, top-5 candidates), then the candidates are mapped back to their original (non-normalized) names and reranked by similarity to the raw query so results read naturally to the user. Validated the system with a dedicated accuracy harness (`accuracy_test.py`) run against a curated set of (query, expected-result) pairs, plus unit tests (`test_utils.py`) covering the normalization utilities, measuring 91.3% top-3 accuracy and 96.3% top-5 accuracy at an average query latency of 1.24ms.

**Tools/Tags:** Python, RapidFuzz, Unidecode, num2words, Fuzzy String Matching, Text Normalization, Unit Testing (unittest)

---

## 3. Semantic Search for Vietnamese Content

**Link:** https://github.com/jaydentrannnn/Semantic-Search-for-Vietnamese-Content

Built a hybrid semantic + keyword search engine over Vietnamese Wikipedia content, combining vector similarity with traditional full-text search so results are relevant both by meaning and by exact term match.

Wrote a scraper (`src/utils.py`) that pulls Vietnamese Wikipedia pages and extracts content specifically under `<h3>` headings, mapping each heading to its associated body text and cleaning/normalizing the extracted text before indexing. Built an embedding stage (`src/embedding.py`) that chunks the cleaned text and encodes it into 768-dimension vectors using the `dangvantuan/vietnamese-document-embedding` SentenceTransformers model, purpose-built for Vietnamese semantic similarity. Implemented the Elasticsearch integration (`src/elastic_search.py`) to store both the raw text and its embedding per chunk, using a Vietnamese-language analyzer with stopword removal for the keyword side. At query time, the search script (`scripts/search.py`) runs a KNN vector search for semantic relevance and a multi-match query for keyword relevance in parallel, then merges the two result sets so exact-term hits and conceptually-related hits both surface. Separated the data-loading path (`scripts/upload_data.py`, which scrapes and indexes fresh content) from the query path so the index can be rebuilt independently of search usage.

**Tools/Tags:** Python, Elasticsearch, Sentence-Transformers, BeautifulSoup4, pyvi (Vietnamese NLP), Vector/KNN Search, Embeddings

---

## 4. Car Assistant Chatbot

**Link:** https://github.com/jaydentrannnn/Car-Assistant-Chatbot

Built a conversational assistant that answers natural-language questions about cars by translating them into SQL against a 3-table database — new car specs (`cars2025`: engine, horsepower, top speed, 0–100 performance, price, fuel type, seats, torque), used car listings (`used_cars_for_sale`: VIN, owner, mileage, condition, service history), and a VIN-linked transaction history table (`car_transaction_history`: seller, buyer, sale date/price, recorded mileage, condition).

Designed the retrieval/generation pipeline in Haystack (`chatbot.py`) around a `ConditionalRouter` that inspects the model's reply each turn and branches: if the reply is prefixed `GENERATE_SQL:`, it routes to a custom `SQLQuery` component that executes against the SQLite database and feeds results back into the prompt; otherwise it routes straight to the conversation memory. Wrote the system prompt (`config.py`) to drive multi-round retrieval: the model first checks whether it already has enough information (from context, prior SQL results, or conversation history) to answer; if not, it generates a targeted SQL query — using `SELECT *` for forward-compatibility, `LIKE` for fuzzy text matches, and `JOIN`s on `VIN` when a question spans tables (e.g., current spec + ownership history) — capped at 5 queries per user turn to bound cost/latency, with an explicit instruction never to fabricate an answer if the data isn't available. Also handled currency normalization (always reporting in USD, converting to VND at a fixed rate when the question is in Vietnamese). Wired in conversational memory (`memory_store.py`, an in-memory chat history store) so follow-up questions and vague references ("that one", "the V8") resolve correctly, and exposed the assistant through a Gradio chat UI with swappable LLM backends: OpenAI `gpt-4.1-mini`, Google `gemini-2.5-flash`, and a self-hosted `Qwen3-8B-AWQ` endpoint via a custom generator class.

**Tools/Tags:** Python, Haystack, OpenAI API, Google Gemini API, Qwen, SQLite, Gradio, Text-to-SQL, RAG, Prompt Engineering

---

## 5. LLM-RL4SQL — Reinforcement Learning Fine-Tuning for Text-to-SQL (CS 175 team project)

**Links:** https://github.com/jaydentrannnn/LLM-RL4SQL · https://github.com/ianbryant2/cs175-project-code

*(Team project — the working repo is hosted under a teammate's account; you're a contributor there, with your own copy at LLM-RL4SQL)*

Built a reinforcement-learning pipeline to fine-tune an LLM for text-to-SQL generation on the Spider benchmark, training with GRPO (Group Relative Policy Optimization) via Hugging Face's `GRPOTrainer`/TRL, with vLLM running in colocated mode for fast on-policy rollout generation (16K-token context, 512-token max completions, batch size 6 per device).

Designed a multi-component reward function (`reward_funcs.py`) rather than a single execution-match signal: a schema-linking reward (Jaccard similarity between the tables/columns referenced in the predicted vs. gold SQL, parsed with `sqlglot`), an n-gram similarity reward (`SequenceMatcher` ratio between tokenized predicted and gold queries via `sqlparse`), a syntax/execution-validity reward (binary — does the query execute without error against a read-only SQLite connection, with a progress-handler timeout guard to kill runaway queries on the training cluster), and a comprehensive execution reward that actually runs the predicted query and scores it as 30% column-set overlap + 70% row-level F1 against the gold result set. Built a `PiecewiseRewardWeightScheduler` that interpolates the weighting across these four components over the course of training — leaning on schema/syntax signals early (when the model rarely produces valid SQL) and shifting weight toward the execution-based reward later (schema/n-gram/syntax/execution weights move from 0.30/0.25/0.35/0.10 to 0.10/0.10/0.10/0.70) — plus a separate `EvalCallback` that periodically swaps in static, non-scheduled reward functions (subset-match and exact-match against held-out data) every 512 steps to get a clean read on model quality mid-training. Set up distributed training for an HPC cluster using Hugging Face Accelerate configs and SLURM batch scripts (`submit_colocate.sh`, `submit_evaluate.sh`), with all runs logged to Weights & Biases, including per-step reward-weight tracking from the scheduler.

**Tools/Tags:** Python, PyTorch, Hugging Face TRL, vLLM, Reinforcement Learning (GRPO), Accelerate, sqlglot, sqlparse, SQLite/SQL, SLURM/HPC, Weights & Biases

---

## 6. DataAlchemy — Multi-Agent Orchestration Backend

**Link:** https://github.com/dolamquan/DataAlchemy

*(Team project — you're a contributing committer alongside two teammates; the repo owner's account is not yours)*

Contributed to a config-driven, multi-agent orchestration backend for coordinating AI/ML workflows across multiple concurrent "portfolio" projects (e.g., running data pipeline, model training, evaluation, and reporting agents in parallel rather than as one hardcoded script).

Agents are defined declaratively in `configs/agents.yaml` (model, instructions, sub-agents, available tools) rather than hardcoded — a root orchestrator agent delegates to specialized sub-agents (planner, data_engineer, ml_engineer, evaluator, project_manager, reporter, infra_ops). The orchestration engine (`app/engine/orchestrator.py`) manages the execution queue, delegates tasks between agents, tracks execution history, and emits live dashboard updates; the agent runtime (`app/engine/agent_runtime.py`) loads each agent's config, resolves its tools and sub-agents, and calls the LLM layer, with every agent returning a structured JSON result (`status`, `summary`, `confidence`, `next_actions`, `artifacts`, `dashboard_update`) so agents can be chained dynamically and audited. Real-time progress, decisions, and system health stream to clients over a WebSocket endpoint (`/ws/portfolio/{portfolio_id}`), while run history and portfolio state persist to PostgreSQL. Agent actions run through a pluggable tool system (`tool_executor.py`) supporting filesystem, shell, Python execution, and HTTP requests, with optional Docker-based isolated execution for sandboxing agent work, and a reporting layer that prepares Power BI-compatible exports.

**Tools/Tags:** Python, FastAPI, PostgreSQL, Docker, WebSockets, YAML Config, Multi-Agent Systems, LLM Orchestration

---

## 7. ZotAssistant — UCI Policy & Course RAG Chatbot

**Link:** https://github.com/jaydentrannnn/ZotAssistant

Built a retrieval-augmented chatbot that helps UCI students navigate course selection, prerequisites, and academic policy, grounded entirely in the official UCI catalogue rather than the model's general knowledge.

Built a BFS crawler to pull ~5,920 courses across 118 departments, 18 schools/divisions' major and minor pages, and student-facing policy pages from UCI's public sites (explicitly excluding staff/HR sites like policies.uci.edu that would pollute results), then ingested the crawled JSON into three separate ChromaDB collections (courses: 235 files / 65MB, majors: 776 files / 168MB, policies: 526 files / 74MB) using Ollama's `nomic-embed-text` for embeddings, with idempotent upsert ingestion so re-crawls don't duplicate data. Designed the query pipeline as an LCEL chain: a rewrite step turns follow-up questions into standalone queries (resolving pronouns like "it"/"that"), an LLM router decides which of the three collections are relevant to the question, retrieval combines direct metadata lookup (so exact codes like "COMPSCI 161" are never missed) with semantic similarity search, a local FlashRank cross-encoder reranks candidates without needing an external API call, and the final answer streams token-by-token over SSE. Handled department-shorthand mapping (e.g., "CS"/"ICS" → "COMPSCI"/"I&C SCI") so casual student phrasing still matches the formal catalogue codes, and added file-upload Q&A (paste a syllabus or advising sheet as PDF/DOCX/TXT and ask questions about it) with an OCR fallback via Tesseract for scanned documents. Built a 6-harness evaluation suite to validate the system end-to-end: router accuracy (collection-selection F1), retrieval quality (Recall@1/3/10, MRR, direct-lookup hit rate), end-to-end faithfulness (citation accuracy plus an LLM-judge score 1–5), multi-turn handling (polarity preservation, pronoun resolution), file-upload correctness, and latency/cost (p50/p95, tokens/query, cost/query). Frontend built in React 18 + Vite + Tailwind CSS + shadcn/ui.

**Tools/Tags:** Python, FastAPI, LangChain, ChromaDB, FlashRank, Ollama, OpenAI API, React, Vite, Tailwind CSS, shadcn/ui, RAG, SSE Streaming, OCR (Tesseract)

---

## 8. Organizational Memory — RAG over the Enron Email Corpus

**Link:** https://github.com/jaydentrannnn/Organizational-Memory

*(Built at an AWS hackathon — team project; verify your specific role before framing as sole builder)*

Built at an AWS hackathon, a RAG system addressing "institutional amnesia" — the loss of undocumented context (why a vendor was blacklisted, why a policy changed) when employees leave — by letting anyone ask natural-language "why" questions over an organization's historical email corpus. Used the Enron email dataset (517K messages) as a real-world proof of concept.

Built the ingestion pipeline to parse raw email headers and bodies from the Kaggle Enron dataset, deduplicate by MD5 hash (517K rows down to ~248K unique emails), and upload the parsed `.txt` files to S3 via 64-way concurrent upload for throughput. Configured an Amazon Bedrock Knowledge Base backed by Titan Embeddings v2 and an OpenSearch Serverless vector store, which syncs directly from the S3 bucket to keep the index current. Wired a query-serving path through a Lambda function (Python 3.11, 60s timeout) that calls Bedrock Nova Pro via the Converse API to generate grounded answers, fronted by an API Gateway HTTP API with CORS enabled, and built a Streamlit frontend (hosted on EC2) so users could ask questions like "What concerns did employees raise about accounting practices?" or "Who was involved in the California energy trading?" and get answers sourced from the actual email corpus rather than model speculation.

**Tools/Tags:** AWS (S3, Bedrock Knowledge Bases, Lambda, API Gateway, OpenSearch Serverless, EC2), Python, RAG, Streamlit, Titan Embeddings v2, Bedrock Nova Pro

---

## 9. AetherMind — Agentic Research System

**Link:** https://github.com/jaydentrannnn/AetherMind

Building an agentic research system that turns a topic into a cited, guardrail-checked report through planning, parallel evidence collection, synthesis, and critique/revision — rather than a single-shot LLM summary.

Designed the agent loop as a LangGraph state machine: a planner breaks the topic into sub-questions, researcher agents fan out in parallel to gather evidence using a registered tool set (`web_search`, `arxiv_search`, `pdf_loader`, `fetch_url`, and sandboxed `code_exec` via E2B), a synthesizer drafts a structured report with source-ID citations, a guardrails stage verifies each citation is actually supported by its source and enforces per-source-domain policy, and a critic performs rubric-based review that can route the graph back to synthesis (revise) or back to research (gather more evidence) before a final memory-writer step persists the approved report — all with bounded revision loops to prevent infinite cycles, and graph state checkpointed via `AsyncSqliteSaver` so long-running jobs survive restarts. Built a task-tagged LLM router on top of LiteLLM (`backend/app/llm/router.py`) so different pipeline stages — planning, synthesis, inner/final critique, preference extraction, entailment checking, eval judging — can each be assigned a different model by cost/capability rather than using one model everywhere. Implemented a memory layer combining SQLite (structured preferences/report history) and ChromaDB (semantic recall) so the system remembers user preferences and prior reports across sessions, added Langfuse + structlog observability, and built an offline evaluation harness supporting deterministic-only, mock-LLM, and full LLM-judge modes for iterating on report quality without always burning API calls. Backend in FastAPI with SSE streaming to a Next.js 15 (App Router) frontend, deployable via Docker Compose.

**Tools/Tags:** Python, LangGraph, LiteLLM, FastAPI, Next.js 15, React, Tailwind, shadcn/ui, SQLite, ChromaDB, Langfuse, pytest, Playwright, SSE, E2B (sandboxed code execution)

---

## 10. ResumeTailor

**Link:** https://github.com/jaydentrannnn/resumetailor

Built a tool that rewrites a resume to match a target job description while preserving the exact visual formatting of the user's original `.docx` template — the layout, fonts, and structure stay identical; only the wording changes.

Implemented a multi-stage LLM pipeline — extract/score, rewrite, and expand — where each stage independently reads from a "master resume" JSON containing every fact the tool is allowed to draw from, so the model can't invent experience that isn't real. Built a model-profile system (`claude`, `ollama`, `lmstudio`, or `hybrid`) letting each of the three stages run on a different backend — for example, using a cheap local Ollama model for extraction/expansion and Claude for the higher-stakes rewrite stage — with CLI flags and web-UI fields to override any single stage's model independently of the chosen profile. Built a template-tagging build step (`build_template.py`) that generates a tagged working template from the user's baseline resume export, so generated content can be mapped back onto the original Word document's exact structure, plus a fit-calibration script (`calibrate.py`) that uses LibreOffice for PDF measurement to make sure the tailored output doesn't overflow the template's spacing. Shipped both a CLI (`tailor.py --jd job.txt`, outputting `.docx` and `.pdf`) and a FastAPI-backed web UI with a hot-reloading frontend for local development, containerized end-to-end with Docker Compose (including host-machine Ollama/LM Studio access via `host.docker.internal`), with a pytest suite that runs without any API key, network access, or Word installation required.

**Tools/Tags:** Python, FastAPI, Docker, python-docx, LLM APIs (Claude / Ollama / LM Studio), CLI Tooling, pytests