# ContractScan

A SaaS contract risk analysis tool that accepts pasted text or a live URL and produces a structured procurement report. Built on FastAPI + LLaMA 3.3 70B (via Groq).

## What it does

Paste in a contract or drop in a URL and ContractScan returns:

- **Overall grade** (A–F) and risk score
- **Clause-by-clause severity ratings** across 9 categories:
  - Auto-Renewal
  - Price Increases
  - Data Ownership
  - Termination Rights
  - Liability Cap
  - Data Portability & Exit
  - Unilateral Changes
  - Governing Law
  - SLA & Remedies
- **Verbatim clause excerpts** from the contract
- **Plain-English explanations** of what each clause means for the buyer
- **Negotiation tips** for high-risk clauses
- **Key dates** and favorable terms

You can also pass a **priority focus** (e.g. "data ownership, exit rights") to weight the analysis toward your biggest concerns.

## Stack

- **Backend:** Python, FastAPI
- **AI:** LLaMA 3.3 70B via Groq API
- **Frontend:** Vanilla JS / HTML
- **Testing:** pytest (74 tests)

## Setup

1. Clone the repo and install dependencies:

```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_api_key_here
```

3. Run the server:

```bash
uvicorn main:app --reload
```

4. Open `http://localhost:8000` in your browser.

## API

### `POST /scan`

```json
{
  "text": "paste contract text here",
  "url": "https://example.com/terms",
  "focus": "optional — e.g. data ownership, exit rights"
}
```

Provide either `text` or `url`, not both. Returns a structured JSON report.

### `GET /health`

Returns `{"status": "ok"}`.

## Tests

```bash
pip install -r test_requirements.txt
pytest
```
