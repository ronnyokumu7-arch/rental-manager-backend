from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.core.errors import NotFoundError, ValidationFailedError
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentMethod, PaymentStatus
from app.routers.invoice import public as public_invoice
from app.routers.payment import actions as payment_actions
from app.schemas.invoice import PublicPaymentCreate


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def unique(self):
        return self

    def first(self):
        return self.value


class FakeSession:
    def __init__(self, results=()):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.results.pop(0) if self.results else None)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _value):
        return None

    async def rollback(self):
        return None


def request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def tenant_invoice() -> Invoice:
    return Invoice(
        id=3,
        tenant_id=7,
        status=InvoiceStatus.sent,
        amount_due=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency_code="KES",
        invoice_number="INV-3",
    )


def pending_payment() -> Payment:
    return Payment(
        id=11,
        tenant_id=7,
        invoice_id=3,
        amount=Decimal("75.00"),
        currency_code="KES",
        method=PaymentMethod.mpesa,
        reference="ABC123",
        status=PaymentStatus.pending,
        paid_at=None,
        recorded_by=None,
    )


@pytest.mark.asyncio
async def test_public_payment_report_stays_pending_and_does_not_change_invoice(monkeypatch):
    invoice = tenant_invoice()
    db = FakeSession([invoice])
    monkeypatch.setattr(public_invoice, "_load_invoice_by_token", lambda *_: _async_value(invoice))
    monkeypatch.setattr(public_invoice, "set_rls_context", lambda *_args, **_kwargs: _async_value(None))
    monkeypatch.setattr(public_invoice, "invalidate_payment_cache", lambda *_: _async_value(None))
    monkeypatch.setattr(
        public_invoice,
        "_build_public_view",
        lambda *_args, **_kwargs: _async_value(SimpleNamespace(payment_reported=True)),
    )

    await public_invoice.record_payment_public.__wrapped__(
        request("/invoices/public/token/pay"),
        "token",
        PublicPaymentCreate(amount=Decimal("100.00"), method=PaymentMethod.mpesa, reference="ABC123"),
        db,
    )

    claim = db.added[0]
    assert claim.status == PaymentStatus.pending
    assert claim.paid_at is None
    assert claim.recorded_by is None
    assert invoice.amount_paid == Decimal("0.00")
    assert invoice.status == InvoiceStatus.sent
    assert db.commits == 1
    assert "invoices.tenant_id = 7" in str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    )


@pytest.mark.asyncio
async def test_confirmation_updates_only_the_payment_tenants_invoice(monkeypatch):
    payment = pending_payment()
    invoice = tenant_invoice()
    db = FakeSession([payment, invoice, payment])

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(payment_actions, "invalidate_payment_cache", no_op)
    monkeypatch.setattr(payment_actions, "invalidate_invoice_cache", no_op)
    monkeypatch.setattr(payment_actions, "invalidate_subscription_cache", no_op)
    monkeypatch.setattr(
        payment_actions.PaymentActivityLogger,
        "on_recorded",
        staticmethod(no_op),
    )

    result = await payment_actions.confirm_payment.__wrapped__(
        request("/payments/11/confirm"),
        11,
        db,
        SimpleNamespace(id=21, tenant_id=7),
    )

    assert result is payment
    assert payment.status == PaymentStatus.completed
    assert payment.paid_at is not None
    assert payment.recorded_by == 21
    assert invoice.amount_paid == Decimal("75.00")
    assert invoice.status == InvoiceStatus.partially_paid
    assert db.commits == 2
    for statement in db.statements[:2]:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id = 7" in sql
        assert statement._for_update_arg is not None


@pytest.mark.asyncio
async def test_confirmation_rejects_payment_from_another_tenant():
    db = FakeSession([None])

    with pytest.raises(NotFoundError):
        await payment_actions.confirm_payment.__wrapped__(
            request("/payments/11/confirm"),
            11,
            db,
            SimpleNamespace(id=21, tenant_id=8),
        )

    sql = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "payments.tenant_id = 8" in sql
    assert db.commits == 0


@pytest.mark.asyncio
async def test_confirmation_rejects_payment_that_exceeds_locked_invoice_balance(monkeypatch):
    payment = pending_payment()
    invoice = tenant_invoice()
    invoice.amount_paid = Decimal("50.00")
    db = FakeSession([payment, invoice])

    with pytest.raises(ValidationFailedError):
        await payment_actions.confirm_payment.__wrapped__(
            request("/payments/11/confirm"),
            11,
            db,
            SimpleNamespace(id=21, tenant_id=7),
        )

    assert payment.status == PaymentStatus.pending
    assert invoice.amount_paid == Decimal("50.00")
    assert db.commits == 0


async def _async_value(value):
    return value
