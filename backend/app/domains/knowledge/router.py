from typing import Annotated
from fastapi import APIRouter,Depends,File,Form,HTTPException,UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.knowledge.ingestion import ingest,reindex
from app.domains.knowledge.models import SourceDocument,SourceDocumentVersion
from app.tools.registry import ToolError
router=APIRouter(prefix="/api/knowledge",tags=["knowledge-ingestion"])
@router.post("/ingest")
async def upload(principal:Annotated[Principal,Depends(require_roles(Role.ENGINEER,Role.SYSTEMS_ENGINEERING))],session:Annotated[AsyncSession,Depends(get_session)],file:UploadFile=File(...),document_key:str=Form(...),title:str=Form(...),revision:str|None=Form(None),acl_labels:str=Form("internal")):
    try:
        row,created=await ingest(session,document_key=document_key,title=title,filename=file.filename or "document.txt",content_type=file.content_type or "application/octet-stream",data=await file.read(),acl_labels=[x.strip() for x in acl_labels.split(",") if x.strip()],revision=revision,user_id=principal.user_id); return {"id":str(row.id),"version":row.version,"status":row.extraction_status,"deduplicated":not created,"error":row.extraction_error}
    except ToolError as exc: raise HTTPException(400,str(exc)) from exc
@router.get("/ingestion")
async def jobs(principal:Annotated[Principal,Depends(require_roles(Role.ENGINEER,Role.SYSTEMS_ENGINEERING))],session:Annotated[AsyncSession,Depends(get_session)]):
    """What is in the index, with the access labels that scope it.

    The title and the ACL travel with the row because the two questions asked
    of an index are "is my document in there" and "who can retrieve it", and a
    filename answers neither.
    """
    rows=(await session.execute(select(SourceDocumentVersion,SourceDocument).join(SourceDocument,SourceDocument.id==SourceDocumentVersion.source_document_id).order_by(SourceDocumentVersion.uploaded_at.desc()))).all()
    return [{"id":str(v.id),"filename":v.filename,"title":d.title,"document_key":d.document_key,"acl_labels":d.acl_labels,"version":v.version,"status":v.extraction_status,"error":v.extraction_error,"uploaded_at":v.uploaded_at} for v,d in rows]
@router.post("/ingestion/{version_id}/reindex")
async def retry(version_id:str,principal:Annotated[Principal,Depends(require_roles(Role.ENGINEER,Role.SYSTEMS_ENGINEERING))],session:Annotated[AsyncSession,Depends(get_session)]): row=await reindex(session,__import__("uuid").UUID(version_id)); return {"id":str(row.id),"status":row.extraction_status}
