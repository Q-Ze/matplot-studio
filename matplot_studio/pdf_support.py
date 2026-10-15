"""Shared synchronization for in-process MuPDF operations."""

import threading


# MuPDF must not be used concurrently by FastAPI's worker threads.
PDF_LOCK = threading.RLock()
