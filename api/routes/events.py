"""Financial & system events REST endpoint."""
from fastapi import APIRouter, Request
from events.event_bus import get_events, get_stats

router = APIRouter(tags=["Events"])


@router.get("/events")
async def list_events(
    limit:    int = 200,
    category: str = "",
    level:    str = "",
):
    """Return financial/system events, newest first.

    Optional filters:
      category — ARBIT | CR9AM | SYSTEM | RISK | TRADE
      level    — INFO | SUCCESS | WARNING | ERROR
    """
    return {
        "events": get_events(
            limit    = min(limit, 1000),
            category = category or None,
            level    = level or None,
        ),
        "stats": get_stats(),
    }
