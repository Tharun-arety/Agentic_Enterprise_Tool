from typing import Annotated
import json
from fastapi import APIRouter,Depends,Header,HTTPException,Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.db import get_session
from app.domains.backoffice.integration import inbox_once,verify_frappe_signature
router=APIRouter(prefix="/api/integrations",tags=["integrations"])
@router.post("/webhooks/frappe")
async def frappe_webhook(request:Request,session:Annotated[AsyncSession,Depends(get_session)],signature:Annotated[str|None,Header(alias="X-Frappe-Webhook-Signature")]=None,event_id:Annotated[str|None,Header(alias="X-Frappe-Event-ID")]=None,event_type:Annotated[str|None,Header(alias="X-Frappe-Event")]=None):
    body=await request.body()
    if not verify_frappe_signature(body,signature,get_settings().frappe_webhook_secret): raise HTTPException(401,"Invalid webhook signature.")
    payload=json.loads(body); row,created=await inbox_once(session,"frappe",event_id or __import__("hashlib").sha256(body).hexdigest(),event_type or payload.get("doctype","unknown"),payload)
    return {"status":"accepted" if created else "duplicate","inbox_id":str(row.id)}
