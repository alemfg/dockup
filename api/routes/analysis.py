"""Analysis context routes — per-(exchange × pair) signal inspection."""
from fastapi import APIRouter, Request
router = APIRouter(tags=["Analysis"])

@router.get("/analysis/contexts")
async def get_contexts(request: Request):
    engine = request.app.state.brain.context_engine
    contexts = engine.get_all_contexts()
    return {"count": len(contexts), "contexts": contexts}

@router.get("/analysis/signals")
async def get_signals(request: Request):
    engine  = request.app.state.brain.context_engine
    signals = engine.get_all_signals()
    return {"count": len(signals), "signals": [s.to_dict() for s in signals]}

@router.get("/analysis/signals/{exchange}/{pair}")
async def get_signal(exchange: str, pair: str, request: Request):
    engine = request.app.state.brain.context_engine
    signal = engine.get_signal(exchange, pair.replace("-", "/"))
    if not signal:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No signal for {exchange}:{pair}")
    return signal.to_dict()
