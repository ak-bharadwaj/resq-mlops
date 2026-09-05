# AI Usage & Verification Log (AI-USAGE.md)

In compliance with Challenge Brief instructions and Section 15:

- **AI Tools Used**: Antigravity Pair Programming Agent (Gemini 3.8 Flash High / Claude 3.7 Sonnet).
- **Scope of Usage**:
  - Synthesizing and formalizing the frozen v25 MLOps architecture contracts.
  - Generating initial project scaffolding, Makefile targets, and JSON schema definitions.
  - Writing automated test suites verifying P0 contracts.
- **Verification & Oversight**:
  - Every architectural contract, timezone boundary (strict UTC), cost calculation (€600/wk delta, fixed €45,600 visit baseline), and tie-breaking rule was manually verified against `LPDG_MLOps_Architecture_v25_CONTRACT_RESTORED_STRENGTHENED_FREEZE.docx` and the official challenge brief.
  - Test suites are run locally with strict assertions to ensure offline execution and zero data leakage.
