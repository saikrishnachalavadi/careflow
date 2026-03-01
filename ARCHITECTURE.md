# CareFlow → Dr.GPT direction

**POC (current):** User message → NLP router (guardrails, intent, Gemini classify) → route.

**Medical path (Dr.GPT-style):** When route = medical:
1. Severity (M0–M3) via Gemini or rules.
2. **Pipeline** (`app/services/medical_pipeline.py`): symptoms → optional AWS Comprehend Medical → PubMed RAG → Gemini with context → educational reply (disclaimer).
3. Same handoff actions (emergency / find doctor / pharmacy) as before.

**Stack:** Gemini 2.5 Flash (classify + reply), PubMed E-utilities (RAG), optional AWS Comprehend Medical. One entry point: `run_medical_pipeline(symptoms, severity)`.
