## Category emphasis: full-stack / AI application

This is a **full-stack or AI-integrated application**. Weight your pass accordingly:

- Favor correctness and safety: input validation, error handling, and clear failure modes
  around API calls, AI providers, and user input.
- Improve developer onboarding docs (env vars, local run, build/test commands).
- Clarify component/module boundaries and naming where they are confusing.
- Add or strengthen tests for any logic you touch; do not break existing tests.
- Do NOT change public APIs, data schemas, or auth flows in this automated pass — flag
  those for humans in the PR description instead.
- Never commit secrets, API keys, or `.env` values.
