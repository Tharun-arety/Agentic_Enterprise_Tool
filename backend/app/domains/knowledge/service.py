from __future__ import annotations
import re
from sqlalchemy import func,or_,select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.embeddings import get_embedding_provider
from app.domains.knowledge.models import DocumentChunk,DocumentType,KnowledgeEmbedding,SourceDocument,SourceDocumentVersion
from app.domains.knowledge.schemas import KnowledgeHit,KnowledgeResponse
from app.domains.pdm.models import Part
from app.tools.registry import ToolError
async def search_engineering_knowledge(session:AsyncSession,query:str,limit:int=5,acl_labels:list[str]|None=None,document_type:str|None=None)->KnowledgeResponse:
    query=query.strip()
    if not query: raise ToolError("Search query is empty.")
    provider=get_embedding_provider(); vector=await provider.embed_one(query); acl=acl_labels or ["internal"]
    base=select(DocumentChunk,SourceDocumentVersion,SourceDocument).join(SourceDocumentVersion,SourceDocumentVersion.id==DocumentChunk.document_version_id).join(SourceDocument,SourceDocument.id==SourceDocumentVersion.source_document_id).where(SourceDocument.acl_labels.overlap(acl))
    if document_type: base=base.where(SourceDocument.document_type==document_type)
    # The deterministic fallback is deliberately not semantic. Letting its
    # arbitrary vectors pull unrelated newly ingested chunks into a result
    # would be worse than using lexical retrieval alone.
    semantic=(await session.execute(base.add_columns(DocumentChunk.embedding.cosine_distance(vector).label("distance")).order_by("distance").limit(max(limit*8,20)))).all() if provider.is_semantic else []
    ts=func.websearch_to_tsquery("english",query)
    # In web-search syntax a hyphen can mean NOT. Engineering identifiers use
    # hyphens heavily, so preserve them as literal evidence terms as well as
    # running the normal full-text query (ECN-26-001, MAG-L-2312, and so on).
    identifiers=set(re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b",query.upper()))
    lexical_conditions=[DocumentChunk.search_vector.op("@@")(ts)]
    for identifier in identifiers:
        lexical_conditions.extend((SourceDocument.document_key.ilike(f"%{identifier}%"),DocumentChunk.text_content.ilike(f"%{identifier}%")))
    lexical=(await session.execute(base.add_columns(func.ts_rank_cd(DocumentChunk.search_vector,ts).label("rank")).where(or_(*lexical_conditions)).order_by(func.ts_rank_cd(DocumentChunk.search_vector,ts).desc()).limit(max(limit*8,20)))).all()
    scores={}; records={}
    for rank,row in enumerate(semantic,1): chunk,ver,doc,distance=row; scores[chunk.id]=scores.get(chunk.id,0)+1/(60+rank); records[chunk.id]=(chunk,ver,doc,1-float(distance))
    for rank,row in enumerate(lexical,1): chunk,ver,doc,_=row; scores[chunk.id]=scores.get(chunk.id,0)+1/(60+rank); records.setdefault(chunk.id,(chunk,ver,doc,0.0))
    hits=[]
    if records:
        ordered=sorted(records,key=lambda x:scores[x],reverse=True)[:limit]
        hits=[KnowledgeHit(document_type=DocumentType.SPEC,text_content=records[i][0].text_content,source_ref=records[i][2].document_key,similarity=round(1-rank*0.001,4),chunk_id=i,source_document_id=records[i][2].id,revision=records[i][1].revision or str(records[i][1].version),page=records[i][0].page,sheet=records[i][0].sheet,heading=records[i][0].heading,rrf_score=round(scores[i],6)) for rank,i in enumerate(ordered,1)]
    remaining=max(0,limit-len(hits))
    if remaining:
        distance=KnowledgeEmbedding.embedding.cosine_distance(vector); rows=(await session.execute(select(KnowledgeEmbedding,distance.label("distance"),Part.part_number).outerjoin(Part,Part.id==KnowledgeEmbedding.related_part_id).order_by(distance).limit(remaining))).all()
        hits.extend(KnowledgeHit(document_type=r.document_type,text_content=r.text_content,source_ref=r.source_ref,related_part_number=p,similarity=round(1-float(d),4)) for r,d,p in rows)
    return KnowledgeResponse(query=query,provider=provider.name,semantic=provider.is_semantic,hits=hits)
