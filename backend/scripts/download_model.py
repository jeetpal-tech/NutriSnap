"""
download_model.py - Download the pinned hsilvosa/nova-group-classifier revision.

Usage:
    cd backend
    python scripts/download_model.py

The model is saved to NOVA_MODEL_DIR (default: backend/models/hsilvosa-nova).
This script is safe to re-run; huggingface_hub skips already-downloaded files.

WARNING: The repo contains a pickled scikit-learn file (nova_gb_model.joblib).
Load only from this pinned, project-controlled revision. Never load user-supplied files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def main() -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: huggingface_hub is not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    repo_id = "hsilvosa/nova-group-classifier"
    revision = settings.nova_model_revision
    local_dir = settings.nova_model_dir

    print(f"Downloading {repo_id}@{revision[:8]} → {local_dir}")
    print("This may take several minutes (~541 MB). Interrupt safely with Ctrl-C.")

    path = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=local_dir,
        ignore_patterns=["*.md", "*.txt", "*.json.lock"],
    )

    print(f"\nModel saved to: {path}")
    print("Run the spike notebook (backend/notebooks/nova_spike.ipynb) next.")


if __name__ == "__main__":
    main()
