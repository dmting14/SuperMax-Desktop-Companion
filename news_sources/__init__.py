"""Independently configurable public RSS sources."""

from .chinanews import SOURCE as CHINANEWS
from .fia import SOURCE as FIA
from .formula1 import SOURCE as FORMULA1
from .fia_documents import SOURCE as FIA_DOCUMENTS
from .sky import SOURCE as SKY

SOURCES = (FIA_DOCUMENTS, FIA, FORMULA1, SKY, CHINANEWS)
