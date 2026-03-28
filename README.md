# Local RAG Assistant — Part 2: Web UI, Memory, and One-Command Startup

> **Branch:** `part-2`
> **Educational Purpose Disclaimer:** This project is for learning and experimentation only. It is not production-ready software. Do not use it to process confidential or regulated data without evaluating it against your organisation's security and compliance requirements.

This branch extends Part 1 with a Streamlit web interface, conversation memory, PDF and DOCX support, and a Podman Compose file for one-command startup.

---

## What's New in Part 2

| Feature | Detail |
|---|---|
| Streamlit UI | Browser-based chat with sidebar document management |
| File uploader | Upload .txt .md .pdf .docx directly from the browser |
| Conversation memory | Last 10 exchanges kept in context for follow-up questions |
| PDF support | PyPDFLoader handles scanned and digital PDFs |
| DOCX support | Docx2txtLoader handles Word documents |
| Podman Compose | Single command starts Oracle + the web app |

---

## Prerequisites

Same as Part 1, plus:
- `podman-compose` installed (`pip install podman-compose`)

---

## Quick Start (Podman Compose)

```bash
# Clone the repo and switch to this branch
git clone https://github.com/YOURUSERNAME/local-rag-oracle.git
cd local-rag-oracle
git checkout part-2

# Copy and fill in credentials
cp .env.example .env

# Start everything
podman-compose up
```

Then open http://localhost:8501 in your browser.

> **First run:** Oracle takes 2-3 minutes to initialise. The app container will wait for it automatically via the healthcheck — you do not need to do anything.

> **First use:** You still need to create the raguser inside Oracle once. See the Oracle User Setup section below.

---

## Oracle User Setup (one-time)

```bash
podman exec -it local-rag-oracle_oracle_1 sqlplus sys/${ORACLE_PWD}@localhost:1521/FREEPDB1 as sysdba
```

```sql
CREATE USER raguser IDENTIFIED BY ragpassword;
GRANT DB_DEVELOPER_ROLE TO raguser;
GRANT UNLIMITED TABLESPACE TO raguser;
EXIT;
```

---

## Running Without Compose

If you prefer to run the app directly without Compose:

```bash
# Install dependencies
pip install -r requirements.txt

# Ingest documents from the command line
python ingest_v2.py

# Start the Streamlit app
streamlit run app.py
```

---

## Using the Interface

**Uploading documents:** Click the uploader in the left sidebar. Supported formats are .txt, .md, .pdf, and .docx. Each file is ingested immediately after upload — no restart needed.

**Asking questions:** Type in the chat input at the bottom. The assistant answers using only the documents in the knowledge base and cites the source files below each response.

**Follow-up questions:** The assistant remembers the last 10 exchanges in the session, so questions like "which of those is most critical?" or "can you expand on the second point?" work as expected.

**Clearing memory:** Click "Clear conversation" in the sidebar to reset the session history. The knowledge base is unaffected.

---

## Project Structure

```
local-rag-oracle/  (part-2 branch)
  app.py               # Streamlit web UI with sidebar and memory
  ingest_v2.py         # Updated ingestion: PDF, DOCX, single-file and bulk modes
  ingest.py            # Original Part 1 ingestion (txt/md only)
  rag_pipeline.py      # Original Part 1 command-line pipeline
  debug.py             # Diagnostic script
  podman-compose.yml   # Full stack in one file
  Dockerfile           # Container image for the Streamlit app
  requirements.txt     # Part 2 dependencies
  .env.example
  .gitignore
  docs/
    .gitkeep
```

---

## Troubleshooting

**App starts but shows no documents in the sidebar**
The knowledge base is empty. Upload a file via the sidebar or run `python ingest_v2.py` from the command line after dropping files into `docs/`.

**PDF pages are showing as separate items in the knowledge base**
This is expected. PyPDFLoader creates one document object per page. The ingestion dedup tracker records the file path, not individual pages, so the file only appears once in the sidebar.

**podman-compose up fails with "service oracle is not ready"**
Oracle 23ai takes 2-3 minutes on first run while it creates the database files. If compose times out before the healthcheck passes, run `podman-compose up` again — the volume is already initialised so it will start much faster.

**ORA-65096 when creating raguser**
Connect to FREEPDB1 not FREE. See the Oracle User Setup section above.

---

## Part of a Series

- **Part 1:** Local RAG with Ollama, LangChain, and Oracle 23ai (`main` branch)
- **Part 2** (this branch): Web UI, memory, PDF/DOCX, Podman Compose
- **Part 3** (coming soon): HuggingFace models, quantisation, LoRA fine-tuning

---

## Licence

MIT
