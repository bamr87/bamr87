# VS Code Launch Configurations

This folder includes `launch.json` with a unified set of debugging configurations for this workspace.

Included groups:

- Docker-first configurations for browser debugging with Microsoft Edge (`msedge`) and server processes.

- Python/Django debug configurations for Docker-run services.

- PostHog-specific configurations (Frontend, Backend, Celery, Plugin Server, Temporal Worker) merged from `posthog/.vscode/launch.json`.

- Inputs:
  - `portNumber`: select the application port (4000, 4002, 8000, 3000).
  - `pickVersion`: used by frontend Jest debug to pick a Node version extension.
  - `temporalTaskQueue`: select a temporal task queue for the Temporal worker.

Compounds:

- `PostHog` compound runs Backend, Celery, Frontend, Plugin Server, and Temporal Worker together — aligned to the PostHog development flow.

Last modified: 2025-11-15
