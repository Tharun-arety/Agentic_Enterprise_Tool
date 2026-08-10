from __future__ import annotations
import asyncio
import httpx
from app.main import app
async def main():
    transport=httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,base_url="http://testserver") as client:
        login=await client.post("/api/auth/login",json={"email":"procurement@magnotherm.test","password":"magnotherm"}); assert login.status_code==200,login.text
        token=login.json()["access_token"]; assert login.json()["expires_in"]==900
        protected=await client.get("/api/procurement/stock-risk",headers={"Authorization":f"Bearer {token}"}); assert protected.status_code==200,protected.text
        denied=await client.get("/api/controlling/variance?fiscal_year=2026",headers={"Authorization":f"Bearer {token}"}); assert denied.status_code==403
        csrf=client.cookies.get("mt_csrf"); refresh=await client.post("/api/auth/refresh",headers={"X-CSRF-Token":csrf}); assert refresh.status_code==200,refresh.text; assert refresh.json()["access_token"]!=token
        logout=await client.post("/api/auth/logout",headers={"Authorization":f"Bearer {refresh.json()['access_token']}"}); assert logout.status_code==200
        revoked=await client.get("/api/procurement/stock-risk",headers={"Authorization":f"Bearer {refresh.json()['access_token']}"}); assert revoked.status_code==401
        print("PASS login, 15-minute access, role denial, CSRF refresh rotation, logout revocation")
if __name__=="__main__": asyncio.run(main())
