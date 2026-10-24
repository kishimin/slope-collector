"""Cooperative maintenance stop at outbound request boundaries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models.control import CollectionPausedError

if TYPE_CHECKING:
    from app.models.control import ControlRepository, Target

LOGGER = logging.getLogger(__name__)


def require_collection_allowed(
    controls: ControlRepository | None, target: Target, paused_sites: set[str]
) -> None:
    """Stop cooperatively after a completed request and its article transaction."""
    if controls is not None and controls.get(target).paused:
        paused_sites.add(target.key)
        LOGGER.info("collection paused target=%s", target.key)
        raise CollectionPausedError
