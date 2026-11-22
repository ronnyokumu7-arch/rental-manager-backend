import os
import base64
import asyncio
import urllib.request
from decimal import Decimal
from typing import Optional, Any
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


async def resolve_signature_data_uri(obj: Any, attr_name: str = "signature_image_path") -> Optional[str]:
    """✅ OPTIMIZED: 3-second timeout prevents event loop blocking."""
    ref = getattr(obj, attr_name, None) if not isinstance(obj, str) else obj
    if not ref:
        return None

    loop = asyncio.get_running_loop()

    def _fetch(url: str) -> Optional[bytes]:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                return resp.read()
        except Exception as e:
            print(f"❌ Failed to fetch signature bytes ({attr_name}): {e}")
            return None

    def _to_data_uri(data: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")

    api_base = get_settings().public_url_base.rstrip("/")
    files_prefix = f"{api_base}/api/v1/files/"
    
    if ref.startswith(files_prefix):
        relative_path = ref[len(files_prefix):].lstrip("/")
        backend = get_backend()
        signed = backend.signed_url(relative_path, ttl_seconds=300)
        if signed:
            data = await loop.run_in_executor(None, _fetch, signed)
            if data:
                return _to_data_uri(data)

        upload_dir = Path(get_settings().uploads_dir).resolve()
        local_path = (upload_dir / relative_path).resolve()
        try:
            local_path.relative_to(upload_dir)
            if local_path.exists() and local_path.is_file():
                with open(local_path, "rb") as f:
                    return _to_data_uri(f.read())
        except ValueError:
            pass
        return None

    if ref.startswith("http://") or ref.startswith("https://"):
        data = await loop.run_in_executor(None, _fetch, ref)
        if data:
            return _to_data_uri(data)
        return None

    if ref.startswith("data:"):
        return ref

    if os.path.exists(ref):
        try:
            with open(ref, "rb") as img_file:
                return _to_data_uri(img_file.read())
        except Exception:
            return None

    return None


async def generate_investor_contract_pdf(contract: InvestorContract, db: AsyncSession) -> bytes:
    # 1. ✅ OPTIMIZED SINGLE QUERY with eager loading
    stmt = (
        select(InvestorContract)
        .options(
            selectinload(InvestorContract.vehicle).selectinload(Vehicle.owner),
            selectinload(InvestorContract.tenant).selectinload(Tenant.profile),
        )
        .where(InvestorContract.id == contract.id)
    )
    result = await db.execute(stmt)
    loaded_contract = result.scalars().unique().first()

    if not loaded_contract:
        raise ValueError("Investor contract not found")

    vehicle = loaded_contract.vehicle
    investor = vehicle.owner if vehicle else None
    tenant = loaded_contract.tenant
    tenant_profile = tenant.profile if tenant else None

    # 2. ✅ SIGNATURES
    investor_signature_uri = None
    agency_signature_uri = None

    if getattr(loaded_contract, "signed_by_investor", False):
        investor_signature_uri = await resolve_signature_data_uri(loaded_contract, "investor_signature_path")
    if getattr(loaded_contract, "signed_by_agency", False):
        agency_signature_uri = await resolve_signature_data_uri(loaded_contract, "agency_signature_path")

    # 3. PREPARE CONTEXT
    context = {
        "contract": loaded_contract,
        "vehicle": vehicle,
        "investor": investor,
        "tenant": tenant,
        "tenant_profile": tenant_profile,
        "investor_signature_uri": investor_signature_uri,
        "agency_signature_uri": agency_signature_uri,
        "total_value": (Decimal(str(loaded_contract.lease_rate)) * Decimal(loaded_contract.duration_months)) 
                       if loaded_contract.duration_months and loaded_contract.lease_rate_type == 'monthly' else None,
    }

    # 4. RENDER HTML
    template = template_env.get_template("investor_contract_premium.html")
    html_content = template.render(**context)

    # 5. ✅ OPTIMIZED PDF GENERATION
    try:
        browser = await browser_pool.get_browser()
        page = await browser.newPage()
        await page.setContent(html_content, {"waitUntil": "networkidle0", "timeout": 5000})

        pdf_bytes = await page.pdf(
            format='A4',
            printBackground=True,
            preferCSSPageSize=True, # ✅ Faster rendering
            margin={'top': '0mm', 'right': '0mm', 'bottom': '0mm', 'left': '0mm'}
        )

        await page.close()
        return pdf_bytes

    except Exception as e:
        error_msg = str(e)
        if "Connection is closed" in error_msg or "Connection closed" in error_msg:
            print("⚠️ Browser died mid-render (investor). Forcing restart and retrying...")
            try:
                browser = await browser_pool.get_browser(force_restart=True)
                page = await browser.newPage()
                await page.setContent(html_content, {"waitUntil": "networkidle0", "timeout": 5000})

                pdf_bytes = await page.pdf(
                    format='A4',
                    printBackground=True,
                    preferCSSPageSize=True,
                    margin={'top': '0mm', 'right': '0mm', 'bottom': '0mm', 'left': '0mm'}
                )
                await page.close()
                return pdf_bytes
            except Exception as retry_err:
                print(f"❌ Investor PDF retry failed: {retry_err}")
                import traceback
                traceback.print_exc()
                raise retry_err

        print(f"❌ PUPPETEER ERROR (Investor Contract): {e}")
        import traceback
        traceback.print_exc()
        raise
