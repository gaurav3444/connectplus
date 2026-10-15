"""Language identification."""

from .detect import Detection, detect, fold, has_cjk, has_vietnamese_diacritics

__all__ = ["Detection", "detect", "fold", "has_cjk",
           "has_vietnamese_diacritics"]
