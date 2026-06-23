"""Forge Engine API route modules.

Each module exposes a FastAPI APIRouter instance:
- project: Project CRUD
- workflow: Workflow control
- artifact: Artifact query
- settings: Configuration management
- files: File tree, content, and token-usage
"""

# Shared registry of active Orchestrator instances, keyed by project_id.
# Populated by project.py (background planning launch) and workflow.py
# (lazy creation on first workflow operation).  Both modules import this
# dict from here, which is safe because routes/__init__.py does not import
# from either sub-module.
_orchestrators: dict = {}
