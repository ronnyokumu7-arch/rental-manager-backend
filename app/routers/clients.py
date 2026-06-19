from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.clients import Client, ClientStatus
from app.models.users import User
from app.schemas.client import ClientCreate, ClientOut, ClientUpdate


router = APIRouter(prefix="/clients", tags=["clients"])


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_client_or_404(client_id: int, tenant_id: int, db: Session) -> Client:
    """Helper to retrieve a client or raise 404 if not found or unauthorized."""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.tenant_id == tenant_id,
    ).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    return client


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(
    client: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    db_client = Client(**client.model_dump(), tenant_id=current_user.tenant_id)
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.get("/", response_model=list[ClientOut])
def read_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Client).filter(
        Client.tenant_id == current_user.tenant_id,
        Client.is_archived == False,
    ).all()


@router.get("/archived", response_model=list[ClientOut])
def read_archived_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Client).filter(
        Client.tenant_id == current_user.tenant_id,
        Client.is_archived == True,
    ).all()


@router.get("/{client_id}", response_model=ClientOut)
def read_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_client_or_404(client_id, current_user.tenant_id, db)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int,
    updates: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = _get_client_or_404(client_id, current_user.tenant_id, db)
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


@router.post("/{client_id}/suspend", response_model=ClientOut)
def suspend_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = _get_client_or_404(client_id, current_user.tenant_id, db)
    if client.status == ClientStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Client is already suspended"
        )
    client.status = ClientStatus.suspended
    db.commit()
    db.refresh(client)
    return client


@router.post("/{client_id}/reactivate", response_model=ClientOut)
def reactivate_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = _get_client_or_404(client_id, current_user.tenant_id, db)
    if client.status == ClientStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Client is already active"
        )
    client.status = ClientStatus.active
    db.commit()
    db.refresh(client)
    return client


@router.post("/{client_id}/archive", response_model=ClientOut)
def archive_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = _get_client_or_404(client_id, current_user.tenant_id, db)
    if client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Client is already archived"
        )
    client.is_archived = True
    client.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(client)
    return client


@router.post("/{client_id}/restore", response_model=ClientOut)
def restore_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = _get_client_or_404(client_id, current_user.tenant_id, db)
    if not client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Client is not archived"
        )
    client.is_archived = False
    client.archived_at = None
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = _get_client_or_404(client_id, current_user.tenant_id, db)
    db.delete(client)
    db.commit()