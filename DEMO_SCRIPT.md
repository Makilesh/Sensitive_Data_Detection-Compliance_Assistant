# Demo Video Script (2–5 minutes)

A suggested walkthrough for recording the required demo video.

**0:00 – 0:20 · Intro**
- "This is the Sensitive Data Detection & Compliance Assistant — a Streamlit app
  that finds sensitive data, scores risk, summarizes compliance, redacts, and
  answers grounded questions, all on the Gemini free tier."
- Show the sidebar: embedding model, models in rotation, live quota panel.

**0:20 – 1:00 · Upload & Findings**
- Upload `data/samples/golden.txt` (or your own PDF).
- Overview tab: format, pages, characters, finding count.
- Findings tab: point out the per-type bar chart and the table — masked values,
  detector provenance (verhoeff/luhn/regex), confidence, page/line.
- Toggle **Reveal raw values** to show privacy-by-default, then untoggle.

**1:00 – 1:30 · Risk**
- Risk tab: the colored **High** badge, the score, and the contributor breakdown
  chart. Explain the weighted + density scoring is deterministic and explainable.

**1:30 – 2:15 · Compliance Summary**
- Summary tab: click **Generate compliance summary**.
- Show the three sections (Observations referencing GDPR/DPDP/PCI-DSS, Security
  Risks, Remediation). Download the Markdown report.

**2:15 – 3:15 · Chat (grounding + refusal)**
- Chat tab. Ask **"How many email addresses are present?"** → note it matches the
  detector exactly (deterministic).
- Ask **"Summarize this document."** → show the grounded answer and expand the
  **Citations** (page/line).
- Ask an out-of-scope question like **"What is the capital of France?"** → show
  the honest **"I don't have enough information"** refusal.

**3:15 – 3:45 · Redaction**
- Redaction tab: side-by-side original vs redacted. Download the redacted file and
  briefly open it to show no sensitive values remain.

**3:45 – 4:30 · Rate-limit rotation & multi-doc**
- Point at the sidebar quota panel: which model served the last call, RPM/RPD
  counters moving. Explain 429 failover across the registry.
- Upload a second document; use the **document switcher**; enable **corpus mode**
  in Chat to query across both. Open the **Audit log** expander (masked entries).

**4:30 – 5:00 · Wrap-up**
- Recap: deterministic + AI detection, rate-limit resilience, grounded RAG,
  privacy by default. Mention the live deployment URL.
