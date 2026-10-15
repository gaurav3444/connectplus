"""Traditional Chinese language layer for connectplus-llm.

Sibling to :mod:`llm.zh` (Simplified). The two scripts are close enough
in structure (Han characters, no whitespace segmentation, no syllable
unit) that ``normalize.py`` and ``readability.py`` are re-exported
unchanged from the Simplified lane rather than duplicated -- both
modules operate on the Unicode Han block as a whole, which covers
Simplified and Traditional characters alike, and neither module reads
the termbase, so nothing here is script-specific to redo.

What genuinely differs between the two lanes is terminology and
register, which is why this package still owns its own
``data/termbase_zh_hant.json`` and its own ``termbase.py``: a Taiwan or
Hong Kong background reader expects 手機/網路/簡訊, not the mainland
手机/网络/短信, and a straight character conversion of the Simplified
termbase would get the script right and the vocabulary wrong.
"""
