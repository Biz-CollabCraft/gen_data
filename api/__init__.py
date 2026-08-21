"""Compatibility namespace for the retired Flask API package.

Operational HTTP control is provided by :mod:`app.main`.  The repository's
current compile smoke still references the top-level ``api`` directory.
"""

from app.main import create_app

__all__ = ["create_app"]
