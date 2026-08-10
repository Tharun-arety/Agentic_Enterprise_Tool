from __future__ import annotations
import uuid
from typing import Literal
from pydantic import BaseModel,Field
class ChatMessage(BaseModel): role:Literal["user","assistant"]; content:str
class ChatRequest(BaseModel): message:str=Field(min_length=1,max_length=4000); history:list[ChatMessage]=Field(default_factory=list,max_length=20)
class RouterDecision(BaseModel): domains:list[str]=Field(max_length=3); rationale:str
class Citation(BaseModel): source_document_id:uuid.UUID|None=None; source_ref:str; revision:str|None=None; page:int|None=None; sheet:str|None=None; heading:str|None=None; chunk_id:uuid.UUID|None=None
class FrameBase(BaseModel): run_id:uuid.UUID|None=None; correlation_id:uuid.UUID|None=None
class AgentStateFrame(FrameBase): agent:str; status:Literal["thinking","delegating","calling_tool","done"]; detail:str|None=None
class TokenFrame(FrameBase): text:str
class ToolResultFrame(FrameBase): tool:str; payload:dict
class FinalFrame(FrameBase): text:str; intent:str; domains:list[str]=Field(default_factory=list); tool_calls:list[str]=Field(default_factory=list); citations:list[Citation]=Field(default_factory=list); proposal_summaries:list[dict]=Field(default_factory=list)
class ErrorFrame(FrameBase): message:str; recoverable:bool=True
