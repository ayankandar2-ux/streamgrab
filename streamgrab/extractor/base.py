"""Extractor plugin interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from ..http import HttpClient
from ..models import MediaInfo


class Extractor(ABC):
    """Base class for URL extractors.

    An extractor inspects a URL and, if it recognises it, returns a
    :class:`~streamgrab.models.MediaInfo` describing the available formats.
    Extractors must not download media; they only resolve metadata.
    """

    name: str = "base"
    #: Higher priority extractors are tried first.
    priority: int = 0

    @abstractmethod
    def matches(self, url: str) -> bool:
        """Return ``True`` if this extractor can handle ``url``."""

    @abstractmethod
    def extract(
        self,
        url: str,
        client: HttpClient,
        headers: Optional[Dict[str, str]] = None,
    ) -> MediaInfo:
        """Resolve ``url`` into a :class:`MediaInfo`."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Extractor {self.name}>"


__all__ = ["Extractor"]
