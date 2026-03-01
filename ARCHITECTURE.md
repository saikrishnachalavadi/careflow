# CareFlow → Medical pipeline

**POC (current):** User message → NLP router (guardrails, intent, Gemini classify) → route.

**Medical path:** When route = medical:
1. Severity (M0–M3) via Gemini.
2. **Pipeline** (`app/services/medical_pipeline.py`): symptoms → Gemini (severity + reply). No RAG, no AWS. Reply step can be swapped for Google Medical API when integrated.
3. Same handoff actions (emergency / find doctor / pharmacy) as before.

**Stack:** Gemini 2.5 Flash (classify + severity + reply). One entry point: `run_medical_pipeline(symptoms)`.
