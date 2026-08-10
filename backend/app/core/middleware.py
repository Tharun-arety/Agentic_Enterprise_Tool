"""Request correlation, authentication boundary and Redis-backed throttling."""
from __future__ import annotations
import json, logging, time, uuid
from collections import defaultdict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.core.config import get_settings
from app.core.security import TokenError, decode_access_token

log=logging.getLogger("magnotherm.http")
_memory: dict[str,deque[float]]=defaultdict(deque)

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request:Request,call_next):
        started=time.perf_counter(); request_id=request.headers.get("x-request-id") or str(uuid.uuid4()); request.state.request_id=request_id
        path=request.url.path
        if path.startswith("/api/") and request.method!="OPTIONS" and path not in {"/api/health","/api/auth/login","/api/auth/refresh","/api/integrations/webhooks/frappe"}:
            value=request.headers.get("authorization","")
            if not value.lower().startswith("bearer "):
                return JSONResponse({"detail":"This endpoint requires a bearer token.","request_id":request_id},401,headers={"WWW-Authenticate":"Bearer","X-Request-ID":request_id})
            try: request.state.claims=decode_access_token(value.split(" ",1)[1])
            except TokenError as exc: return JSONResponse({"detail":str(exc),"request_id":request_id},401,headers={"WWW-Authenticate":"Bearer","X-Request-ID":request_id})
        if path.startswith("/api/"):
            allowed=await _allow(request)
            if not allowed: return JSONResponse({"detail":"Rate limit exceeded.","request_id":request_id},429,headers={"Retry-After":"60","X-Request-ID":request_id})
        response=await call_next(request); response.headers["X-Request-ID"]=request_id
        log.info(json.dumps({"event":"http_request","request_id":request_id,"method":request.method,"path":path,"status":response.status_code,"duration_ms":round((time.perf_counter()-started)*1000,2)}))
        return response

async def _allow(request:Request)->bool:
    settings=get_settings(); subject=getattr(request.state,"claims",{}).get("sub") if hasattr(request.state,"claims") else None; key=f"rate:{subject or request.client.host if request.client else 'unknown'}:{int(time.time()//60)}"
    try:
        import redis.asyncio as redis
        client=redis.from_url(settings.redis_url,encoding="utf-8",decode_responses=True,socket_connect_timeout=.2,socket_timeout=.2)
        count=await client.incr(key)
        if count==1: await client.expire(key,61)
        await client.aclose(); return int(count)<=settings.rate_limit_per_minute
    except Exception:
        now=time.time(); q=_memory[key]
        while q and q[0]<now-60: q.popleft()
        if len(q)>=settings.rate_limit_per_minute: return False
        q.append(now); return True
