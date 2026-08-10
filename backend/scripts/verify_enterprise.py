from __future__ import annotations
import asyncio
from sqlalchemy import select
from app.core.db import dispose_engine,get_session_factory
from app.domains.controlling.models import CostRollupSnapshot
from app.domains.controlling.service import rollup_cost,variance_report
from app.domains.ecm.models import ChangeNotice,ChangeOrder,ChangeRequest,EcoStatus,EcrStatus
from app.domains.knowledge.service import search_engineering_knowledge
from app.domains.procurement.service import affected_units,supply_risk
from app.domains.qms.models import NonConformance
async def main():
    async with get_session_factory()() as session:
        cost=await rollup_cost(session,"ECL-SYS-1000",10)
        assert cost.material_cost>0 and cost.labour_cost>0 and cost.total_cost==round(cost.material_cost+cost.labour_cost,4)
        risks=await supply_risk(session); assert any(x["part_number"]=="MAG-ND-050" and x["low_stock"] for x in risks)
        units=await affected_units(session,"MAG-L-2312"); assert {x["serial_number"] for x in units}=={"ECL-M-097"}
        variance=await variance_report(session,2026); assert variance and variance[0].variance==435280
        ncr=(await session.execute(select(NonConformance).where(NonConformance.number=="NCR-26-001"))).scalar_one()
        ecr=(await session.execute(select(ChangeRequest).where(ChangeRequest.number=="ECR-26-002"))).scalar_one()
        eco=(await session.execute(select(ChangeOrder).where(ChangeOrder.change_request_id==ecr.id))).scalar_one()
        ecn=(await session.execute(select(ChangeNotice).where(ChangeNotice.change_order_id==eco.id))).scalar_one()
        snapshots=(await session.execute(select(CostRollupSnapshot).where(CostRollupSnapshot.eco_id==eco.id).order_by(CostRollupSnapshot.captured_at))).scalars().all()
        assert ncr.escalated_ecr_id==ecr.id and ecr.status is EcrStatus.CONVERTED
        assert eco.status is EcoStatus.RELEASED and ecn.number=="ECN-26-001"
        assert len(snapshots)==2 and float(snapshots[1].total_cost)>float(snapshots[0].total_cost)
        knowledge=await search_engineering_knowledge(session,"ECN-26-001 MAG-L-2312",limit=3)
        assert knowledge.hits
        citation=next((hit for hit in knowledge.hits if hit.source_ref=="ECN-26-001"),None)
        assert citation is not None, [hit.source_ref for hit in knowledge.hits]
        assert citation.revision=="A" and citation.source_document_id is not None
        print(f"PASS {ncr.number}->{ecr.number}->{eco.number}->{ecn.number}; cost EUR {cost.total_cost:.4f}; lot trace {units[0]['serial_number']}; variance EUR {variance[0].variance:.2f}; citation {citation.source_ref} rev {citation.revision}")
    await dispose_engine()
if __name__=="__main__": asyncio.run(main())
