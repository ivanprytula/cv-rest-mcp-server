"""Document kind constants.

In the DB-backed version, this module also contains the SQLAlchemy DocumentRow
ORM model. For api-core without DB, we only need the kind constants.
"""

from __future__ import annotations


# Document kinds. Each is a whole JSON document the operator edits.
KIND_CV = "cv"
KIND_SKILL_BANK = "skill_bank"
KIND_JD_VOCABULARY = "jd_vocabulary"

DOCUMENT_KINDS = (KIND_CV, KIND_SKILL_BANK, KIND_JD_VOCABULARY)
