from __future__ import annotations

import re
from collections.abc import Mapping

from guardrails_text2sql.models import AmbiguityOption, ClarificationRequest


class AmbiguityDetector:
    def __init__(self, glossary: Mapping[str, tuple[AmbiguityOption, ...]] | None = None) -> None:
        self.glossary = {term.lower(): options for term, options in (glossary or {}).items()}

    def detect(self, question: str) -> ClarificationRequest | None:
        normalized = question.lower()
        for term, options in self.glossary.items():
            if re.search(rf"\b{re.escape(term)}\b", normalized):
                if any(re.search(rf"\b{re.escape(option.label.lower())}\b", normalized) for option in options):
                    continue
                return ClarificationRequest(
                    term=term,
                    question=f'When you say "{term}", which definition should I use?',
                    options=options,
                )
        return None
