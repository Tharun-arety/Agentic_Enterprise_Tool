"""Imports every module that declares a table, so the mapper registry is whole.

`Base.metadata.create_all` and Alembic's autogenerate only know about tables
whose module has been imported. Relationships declared with string targets
("Part", "LabTestRecord") resolve at mapper-configuration time, which means a
module missing from this list produces an `InvalidRequestError` naming a class
that looks like it exists — a confusing failure with a boring cause.

One import site, so adding a domain is one line here rather than a hunt through
whichever entrypoint happened to break first.
"""

from app.core.audit import AuditEvent  # noqa: F401
from app.core.proposals import AgentProposal  # noqa: F401
from app.agents.models import AgentRun, ToolInvocation  # noqa: F401
from app.evals.models import EvalCaseResult, EvalRun  # noqa: F401
from app.workers.models import AutomationFinding  # noqa: F401
from app.domains.ecm.models import (  # noqa: F401
    ChangeAffectedItem,
    ChangeBoardReview,
    ChangeNotice,
    ChangeNoticeAcknowledgement,
    ChangeOrder,
    ChangeOrderLine,
    ChangeRequest,
    ImpactAssessment,
)
from app.domains.identity.models import AccessTokenRevocation, RefreshSession, User  # noqa: F401
from app.domains.knowledge.models import DocumentChunk, KnowledgeEmbedding, SourceDocument, SourceDocumentVersion  # noqa: F401
from app.domains.backoffice.models import ExternalReference, IntegrationOutbox, WebhookInbox  # noqa: F401
from app.domains.procurement.models import GoodsReceipt, PurchaseOrder, PurchaseOrderLine, ReceiptLot, StockPosition, Supplier  # noqa: F401
from app.domains.crm.models import CustomerSite, DeployedUnit, FieldEvent, Lead, Opportunity  # noqa: F401
from app.domains.programs.models import ConsortiumPartner, Deliverable, Milestone, Program, TrlGate, WorkPackage  # noqa: F401
from app.domains.assets.models import AssetBooking, CalibrationCertificate, LabAsset, TestAssetUsage  # noqa: F401
from app.domains.resources.models import EngineerCapacity, ResourceAllocation, TimesheetEntry  # noqa: F401
from app.domains.controlling.models import Actual, Budget, Commitment, CostCentre, CostRollupSnapshot, CostTarget, WorkCentreRate  # noqa: F401
from app.domains.pdm.models import (  # noqa: F401
    BomEdge,
    ConfigurationBaseline,
    Document,
    DocumentRevision,
    MbomDelta,
    Operation,
    Part,
    PartRevision,
)
from app.domains.qms.models import (  # noqa: F401
    CapaAction,
    LabTestRecord,
    NonConformance,
    TestProtocol,
    TestSpecLimit,
    Unit,
    UnitComponent,
)

__all__ = [
    "AgentProposal",
    "AuditEvent",
    "BomEdge",
    "CapaAction",
    "NonConformance",
    "TestProtocol",
    "TestSpecLimit",
    "Unit",
    "UnitComponent",
    "ChangeAffectedItem",
    "ChangeBoardReview",
    "ChangeNotice",
    "ChangeNoticeAcknowledgement",
    "ChangeOrder",
    "ChangeOrderLine",
    "ChangeRequest",
    "ImpactAssessment",
    "ConfigurationBaseline",
    "Document",
    "DocumentRevision",
    "KnowledgeEmbedding",
    "LabTestRecord",
    "MbomDelta",
    "Operation",
    "Part",
    "PartRevision",
    "User",
    "RefreshSession",
    "AccessTokenRevocation",
]
