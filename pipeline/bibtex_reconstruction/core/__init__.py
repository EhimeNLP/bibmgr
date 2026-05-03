# core/__init__.py

"""
Core Utilities and Configurations Package.
"""

from .utils import calculate_similarity
from .config import settings

__all__ = [
    "calculate_similarity",
    "settings",
]