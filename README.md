# GST Practice Copilot – India
### Full-Stack Local-First AI GST Legal Research & Advisory Agent

**GST Practice Copilot** is a production-grade, local-first legal research application designed for Indian Chartered Accountants (CAs), CA firms, tax advocates, GST practitioners, and article assistants. 

It executes deep, date-aware statutory legal research, verifies provisions across official CBIC and GSTN databases, audits judicial precedents, and synthesizes authoritative 12-section GST legal research memorandums.

---

## 🏛️ Key Capabilities

- **Date-Aware Statutory Interpretation**: Distinguishes notification date, publication date, effective date, and applicable law for specific historical tax periods (e.g., Section 16(4) time-limit changes and retrospective relief under Section 16(5)/(6) introduced by Finance (No. 2) Act, 2024).
- **Official Domain Allowlist**: Discovers and fetches documents strictly from approved official sources (`taxinformation.cbic.gov.in`, `cbic.gov.in`, `gst.gov.in`, `gstcouncil.gov.in`, and Supreme Court/High Court portals).
- **SSRF & Privacy Protection**: Automatic private IP filtering (anti-SSRF) and query sanitization (stripping client GSTINs, PANs, phone numbers, and emails before transmitting searches).
- **OpenAI-Compatible Local-First Architecture**: Standardized on `langchain-openai.ChatOpenAI`. Runs against any local endpoint (Ollama, vLLM, llama.cpp) or private cloud without hardcoding model names or vendor locks.
- **Graceful Unconfigured Mode**: Starts cleanly without an LLM running, delivering structured setup guidance instead of crashing.
- **Local Filesystem Persistence**: No external SQL or vector databases required. Uses process-safe, atomic JSONL for conversations, structured JSON for metadata, and Markdown for memorandums with `filelock`.
- **Role-Tailored Memorandums**: Prioritizes checklists and procedural depth for the active user role (**Partner / Counsel**, **Senior Executive**, or **Intern / Article Assistant**).
- **No Hallucinated Math**: No calculation tools or unverified arithmetic agents; strictly focuses on legal interpretation and statutory compliance.

---

## 🏗️ Architecture Overview

The system is organized into three clean, decoupled layers:

```
┌────────────────────────────────────────────────────────┐
│               Layer A: Streamlit UI                    │
│   - Role selection (Partner / Senior / Intern)         │
│   - Expandable evidence & clickable citation viewer    │
│   - Streaming research step indicators                 │
│   - Markdown memorandum export                         │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP / SSE REST
┌──────────────────────────▼─────────────────────────────┐
│               Layer B: FastAPI Backend                 │
│   - /api/v1/chat & /api/v1/chat/stream (SSE)           │
│   - /api/v1/conversations (JSONL CRUD)                 │
│   - /api/v1/documents/upload (PDF/Text)                │
│   - /api/v1/health & /api/v1/config/status             │
└──────────────────────────┬─────────────────────────────┘
                           │ Graph Invocation
┌──────────────────────────▼─────────────────────────────┐
│          Layer C: LangGraph Research Engine            │
│  1. load_conversation      8. document_extractor       │
│  2. query_understanding    9. evidence_compiler        │
│  3. fact_extraction       10. legal_analysis           │
│  4. research_planner      11. citation_validator       │
│  5. search_query_gen      12. answer_generator         │
│  6. official_source_search 13. persistence_node        │
│  7. source_fetcher                                     │
└────────────────────────────────────────────────────────┘
```


---

## 🔄 The 13-Node LangGraph Pipeline

1. **`load_conversation`**: Loads past turns from `data/conversations/{id}.jsonl` using `filelock`.
2. **`query_understanding`**: Classifies multi-topic GST queries, relevant financial years, tax periods, and jurisdictions.
3. **`fact_extraction`**: Isolates material facts, uploaded attachments, and formulates clear assumptions.
4. **`research_planner`**: Outlines target Acts (CGST/IGST), Rules, Notifications, Circulars, and Precedents.
5. **`search_query_generation`**: Formulates sanitized search queries restricted to official domains.
6. **`official_source_search`**: Discovers official documents via search adapter (local SearXNG or hermetic test mock).
7. **`source_fetcher`**: Retrieves original web pages and PDFs via HTTPX with SSRF and redirect guards.
8. **`document_extractor`**: Parses HTML (BeautifulSoup4) and PDF (PyMuPDF) with SHA-256 document hashing.
9. **`evidence_compiler`**: Synthesizes verified excerpts, assigning stable IDs (`SRC-001`, `SRC-002`).
10. **`legal_analysis`**: Evaluates statutory hierarchy (Supreme Court vs High Courts vs AAR) and date validity.
11. **`citation_validator`**: Cross-checks claims against compiled evidence to eliminate hallucinated citations. Triggers refinement if evidence is insufficient.
12. **`answer_generator`**: Assembles the complete 12-section GST Research Memorandum (Sections A to L).
13. **`persistence_node`**: Persists conversation records and structured session artifacts to the local filesystem.

---

## 📋 Standard 12-Section Memorandum Format

Every generated research output contains:
- **A. Executive Conclusion**: Direct answer ([PERMITTED] / [NOT PERMITTED] / [PERMITTED SUBJECT TO CONDITIONS] / [FURTHER VERIFICATION REQUIRED]).
- **B. Facts and Assumptions**: Supplied factual matrix and explicit professional assumptions.
- **C. Issues Involved**: Itemized legal and compliance questions.
- **D. Applicable Legal Provisions**: Sections, rules, notifications, circulars, and judicial precedents.
- **E. Detailed Legal Analysis**: Date-aware statutory interpretation and judicial standing.
- **F. Practical Approach**: CA firm strategy and procedural recommendations.
- **G. Returns and Compliance**: Affected return tables (GSTR-1, GSTR-3B, GSTR-9/9C) and disclosures.
- **H. GST Portal Procedure**: Actual verified steps on `gst.gov.in`.
- **I. Documentation Checklist**: Invoices, delivery challans, e-way bills, and CA certificates to maintain.
- **J. Risk Analysis & Litigation Exposure**: Exposure under Sections 50, 73, 74, 122, and 125.
- **K. Action Checklist**: Demarcated checklists for Intern, Senior Executive, and Partner/Counsel.
- **L. Legal References**: Authoritative citations with clickable links and SHA-256 document hashes.

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.11 or later** (Tested on Python 3.12.3)
- Standard Python virtual environment tools (`venv` and `pip`)

### 2. Environment Setup

```bash
# Clone or navigate to the workspace
cd /mnt/storage/Downloads/GST_AGENT

# Create virtual environment
python3 -m venv .venv

# Activate the virtual environment
# On Linux / macOS:
source .venv/bin/activate

# On Windows (cmd.exe):
# .venv\Scripts\activate.bat
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# Upgrade pip and install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configuration (`.env`)

Copy `.env.example` to `.env` (or configure your existing `.env`):

```bash
cp .env.example .env
```

#### Key Configuration Variables:

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | Provider protocol | `openai_compatible` |
| `LLM_BASE_URL` | Base URL of OpenAI-compatible inference endpoint | *(Empty by default)* |
| `LLM_API_KEY` | Optional API token for inference server | *(Empty or `none`)* |
| `LLM_MODEL` | Served model name | `default` |
| `LLM_TEMPERATURE` | Generation temperature | `0.0` |
| `LLM_REASONING_EFFORT` | Reasoning effort passed to thinking models (`none`, `low`, `medium`) | `low` |
| `RESEARCH_LLM_REASONING_EFFORT` | Reasoning effort for query planner (`understand_query`) | `none` |
| `SEARCH_PROVIDER` | Search adapter (`searxng` or `mock`) | `searxng` |
| `SEARXNG_BASE_URL` | Base URL of local or private SearXNG instance | `http://localhost:8080` |
| `SEARXNG_TIMEOUT` | SearXNG HTTP request timeout in seconds | `30` |
| `SEARXNG_ENGINES` | Optional comma-separated SearXNG engines override | `bing,yahoo` |
| `SEARXNG_FALLBACK_ENGINES` | Semicolon-separated fallback engine groups rotated on rate limit/CAPTCHA | `duckduckgo,startpage;brave,mojeek` |
| `SEARCH_CACHE_TTL_SECONDS` | Persistent SearXNG search cache TTL in seconds (`0` disables) | `3600` |
| `SOURCE_CACHE_TTL_SECONDS` | Persistent URL fetch cache TTL in seconds (`0` disables) | `21600` |
| `ENFORCE_OFFICIAL_DOMAINS` | Restrict Tier 1/2 fetching to `config/sources.yaml` | `true` |
| `ALLOW_UNVERIFIED_FALLBACK` | Enable Tier 3 open-web fallback when Tier 1 & 2 miss | `false` |
| `DATA_DIR` | Local storage root path | `./data` |

#### Example LLM Configurations:

**Ollama (Local)**:
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:14b
LLM_API_KEY=none
```

**vLLM / llama.cpp (Local or Cloud VM)**:
```env
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_MODEL=your_model_name
LLM_API_KEY=none
```

**DeepInfra (Serverless Cloud)**:
```env
LLM_BASE_URL=https://api.deepinfra.com/v1
LLM_API_KEY=your_deepinfra_api_token
LLM_MODEL=Qwen/Qwen2.5-14B-Instruct
```

---

## 🏃 Running the Application

Launch the backend and frontend in separate terminal windows:

### Terminal 1: Launch FastAPI Backend
```bash
source .venv/bin/activate
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
# Or via script:
./scripts/run_backend.sh
```
*Backend will be accessible at: `http://127.0.0.1:8000` (API Docs at `http://127.0.0.1:8000/docs`)*

### Terminal 2: Launch Streamlit Dashboard
```bash
source .venv/bin/activate
streamlit run frontend/app.py --server.port 8501
# Or via script:
./scripts/run_frontend.sh
```
*Frontend UI will open at: `http://localhost:8501`*

---

## 🧪 Testing & Code Quality

The test suite includes 25 comprehensive automated tests mocking external networks and LLM calls so all tests run hermetically:

```bash
source .venv/bin/activate

# Run full pytest test suite
pytest -v

# Run Ruff code quality and style checks
ruff check .
```

---

## 📂 Project Structure

```
GST_AGENT/
├── backend/
│   └── app/
│       ├── main.py                     # FastAPI application entrypoint
│       ├── api/                        # REST & SSE streaming routers
│       │   ├── chat.py                 # Chat & SSE endpoint (/chat, /chat/stream)
│       │   ├── conversations.py        # Conversation CRUD (/conversations)
│       │   └── research.py             # Research artifact viewer (/research/{id})
│       ├── agents/
│       │   ├── graph.py                # LangGraph 5-node tiered state graph
│       │   ├── state.py                # Pydantic ResearchState definition
│       │   ├── prompts.py              # GST legal research prompts (<26B hardened)
│       │   └── nodes/                  # 5 LangGraph orchestration nodes
│       ├── llm/
│       │   └── factory.py              # ChatOpenAI factory & health checker
│       ├── tools/
│       │   ├── source_validator.py     # SSRF filter & 3-tier domain validator
│       │   ├── fetcher.py              # Async HTTPX safe document fetcher
│       │   ├── html_parser.py          # BeautifulSoup4 statutory extractor
│       │   ├── pdf_parser.py           # PyMuPDF notification/circular extractor
│       │   ├── evidence_extractor.py   # BM25 passage scorer & tier escalation
│       │   └── search/                 # Provider-independent search
│       │       ├── base.py             # Search interface & privacy sanitizer
│       │       ├── searxng_adapter.py  # SearXNG tiered search adapter
│       │       └── mock_adapter.py     # Offline GST test adapter
│       ├── storage/                    # Filesystem persistence engine
│       │   ├── conversations.py        # Thread-safe JSONL conversation store
│       │   ├── research.py             # Structured research session store
│       │   └── source_cache.py         # Download cache with SHA-256 indexing
│       ├── schemas/                    # Pydantic API schemas
│       └── core/                       # Config & correlated logging utilities
│
├── frontend/
│   ├── app.py                          # Streamlit application dashboard
│   ├── components/
│   │   ├── sidebar.py                  # Persona selector & conversation history
│   │   └── evidence_panel.py           # Expandable tiered source evidence viewer
│   └── services/
│       └── api_client.py               # HTTP/SSE client connecting to FastAPI
│
├── config/
│   └── sources.yaml                    # 3-tier GST authority & secondary source registry
├── data/                               # Local-first persistence (excluded from Git)
│   ├── conversations/                  # JSONL conversation histories
│   ├── research_sessions/              # Persisted research & diagnostic artifacts
│   └── downloaded_sources/             # Raw cached documents by authority
├── tests/                              # Automated Pytest suite (25 tests)
├── scripts/                            # Runner shell scripts
├── .env.example                        # Template environment variables
├── .env                                # Active environment configuration
├── .gitignore                          # Protected files & secrets
├── requirements.txt                    # Python dependencies
├── pytest.ini                          # Pytest configuration
├── ruff.toml                           # Code quality configuration
└── README.md                           # Documentation
```

---

## 🔒 Security & Professional Disclaimers

1. **Anti-SSRF & Network Isolation**: Only approved domains in `config/sources.yaml` can be fetched. DNS resolution is performed and private/loopback/link-local IP addresses are blocked.
2. **Client Confidentiality**: The search query sanitizer strips 15-digit GSTINs, 10-digit PANs, email addresses, and phone numbers before any query is dispatched to third-party search APIs.
3. **No Professional Liability**: This application is an assistive research copilot for qualified tax practitioners. All legal interpretations must be independently reviewed by a qualified Chartered Accountant or Advocate before being presented in client opinions, returns, or court submissions.
