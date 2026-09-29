import os
import base64
import asyncio
import urllib.request
from decimal import Decimal
from typing import Optional
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.investor_contracts import InvestorContract
from app.models.vehicles import Vehicle
from app.models.users import User
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile
from app.services.browser_pool import browser_pool
from app.services.storage import get_backend

BASE_DIR = Path(__file__).resolve().parent.parent
template_env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(['html', 'xml'])
)


async def resolve_signature_data_uri(signature_ref: Optional[str]) -> Optional[str]:
    """
    ✅ BULLETPROOF SIGNATURE RESOLVER (backend-aware)
    Adapted for investor contracts. Resolution order:
      1. API files URL → Cloudinary: backend.signed_url() then fetch bytes
                         Local disk: read uploads_dir/{relative_path} directly
      2. Direct http(s) URL → fetch bytes
      3. Data URI stored directly → return as-is
      4. Legacy local file path → read from disk if it still exists
    """
    if not signature_ref:
        return None

    loop = asyncio.get_running_loop()

    def _fetch(url: str) -> Optional[bytes]:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return resp.read()
        except Exception as e:
            print(f"❌ Failed to fetch signature bytes: {e}")
            return None

    def _to_data_uri(data: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")

    # 1. ✅ Authenticated API URL produced by upload_file()
    api_base = get_settings().public_url_base.rstrip("/")
    files_prefix = f"{api_base}/api/v1/files/"
    if signature_ref.startswith(files_prefix):
        relative_path = signature_ref[len(files_prefix):].lstrip("/")

        # a) Cloudinary backend → short-lived signed URL → fetch bytes
        backend = get_backend()
        signed = backend.signed_url(relative_path, ttl_seconds=300)
        if signed:
            data = await loop.run_in_executor(None, _fetch, signed)
            if data:
                return _to_data_uri(data)

        # b) Local backend → read from disk
        upload_dir = Path(get_settings().uploads_dir).resolve()
        local_path = (upload_dir / relative_path).resolve()
        try:
            local_path.relative_to(upload_dir)  # safety: no path traversal
            if local_path.exists() and local_path.is_file():
                with open(local_path, "rb") as f:
                    return _to_data_uri(f.read())
        except ValueError:
            pass

        print(f"⚠️ Could not resolve signature via storage backend: {signature_ref}")
        return None

    # 2. Direct Cloudinary / public http(s) URL
    if signature_ref.startswith("http://") or signature_ref.startswith("https://"):
        data = await loop.run_in_executor(None, _fetch, signature_ref)
        if data:
            return _to_data_uri(data)
        return None

    # 3. Data URI stored directly in the column
    if signature_ref.startswith("data:"):
        return signature_ref

    # 4. Legacy local file path
    if os.path.exists(signature_ref):
        try:
            with open(signature_ref, "rb") as img_file:
                return _to_data_uri(img_file.read())
        except Exception as e:
            print(f"❌ Error encoding local signature: {e}")
            return None

    print(f"⚠️ Signature reference unusable: {signature_ref}")
    return None


async def generate_investor_contract_pdf(contract: InvestorContract, db: AsyncSession) -> bytes:
    # 1. ASYNC DATA FETCHING
    vehicle_stmt = select(Vehicle).where(Vehicle.id == contract.vehicle_id)
    vehicle = (await db.execute(vehicle_stmt)).scalars().first()

    investor = None
    if vehicle and vehicle.owner_id:
        investor_stmt = select(User).where(User.id == vehicle.owner_id)
        investor = (await db.execute(investor_stmt)).scalars().first()

    tenant_stmt = select(Tenant).where(Tenant.id == contract.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()

    tenant_profile = None
    if tenant:
        profile_stmt = select(TenantProfile).where(TenantProfile.tenant_id == tenant.id)
        tenant_profile = (await db.execute(profile_stmt)).scalars().first()

    # 2. ✅ SIGNATURES: resolve via storage service (survives deploys)
    investor_signature_uri = None
    agency_signature_uri = None
    
    if getattr(contract, "signed_by_investor", False):
        investor_signature_uri = await resolve_signature_data_uri(getattr(contract, "investor_signature_path", None))
    if getattr(contract, "signed_by_agency", False):
        agency_signature_uri = await resolve_signature_data_uri(getattr(contract, "agency_signature_path", None))

    # 3. PREPARE CONTEXT FOR JINJA2 TEMPLATE
    context = {
        "contract": contract,
        "vehicle": vehicle,
        "investor": investor,
        "tenant": tenant,
        "tenant_profile": tenant_profile,
        "investor_signature_uri": investor_signature_uri,
        "agency_signature_uri": agency_signature_uri,
        "total_value": (Decimal(str(contract.lease_rate)) * Decimal(contract.duration_months)) 
                       if contract.duration_months and contract.lease_rate_type == 'monthly' else None,
    }

    # 4. RENDER HTML
    template = template_env.get_template("investor_contract_premium.html")
    html_content = template.render(**context)

    # 5. OPTIMIZED PDF GENERATION WITH BROWSER POOL
    try:
        browser = await browser_pool.get_browser()
        page = await browser.newPage()
        await page.setContent(html_content)
        await asyncio.sleep(0.3) # Allow fonts/styles to settle

        pdf_bytes = await page.pdf(
            format='A4',
            printBackground=True,
            margin={
                'top': '15mm',
                'right': '15mm',
                'bottom': '15mm',
                'left': '15mm'
            }
        )

        await page.close() # Note: browser_pool usually handles page cleanup, but explicit is safe
        return pdf_bytes

    except Exception as e:
        print(f"❌ PUPPETEER ERROR (Investor Contract): {e}")
        import traceback
        traceback.print_exc()
        raise
