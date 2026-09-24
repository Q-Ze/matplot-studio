"""Run Matplot Studio with ``python -m matplot_studio``."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "matplot_studio.app:app",
        host=os.environ.get("MATPLOT_STUDIO_HOST", "127.0.0.1"),
        port=int(os.environ.get("MATPLOT_STUDIO_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
