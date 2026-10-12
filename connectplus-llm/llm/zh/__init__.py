"""The Chinese lane: terminology, register, readability, normalisation.

Parallel in structure to llm/vi/. Everything here is language-specific and
reached through llm/lanes.py, never imported directly by the stages.
"""

from . import normalize, readability, termbase

__all__ = ["normalize", "readability", "termbase"]
