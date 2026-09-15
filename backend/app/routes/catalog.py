"""Catalog entries: the sources and sinks jobs are built from."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from ..ddl import Column, DdlError, build_create_table, options_from_json, options_to_json
from ..deps import (
    current_principal,
    get_gateway,
    get_registry,
    get_secret_store,
    require_writer,
)
from ..guards import check_catalog_entry, columns_of, parse_options
from ..models import CatalogEntry, Job
from ..gateway import SqlGatewayClient
from ..preview import sample_source
from ..registry import ConnectorRegistry
from ..schemas import (
    CatalogEntryIn,
    CatalogEntryOut,
    ColumnOut,
    NestedFieldOut,
    SampleOut,
    WarningOut,
)
from ..secrets import SecretStore

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _options_of(entry: CatalogEntry) -> dict[str, str]:
    """The entry's options, from the form values or read back out of the DDL.

    An entry created from hand-written SQL -- which is how anything imported or
    scripted arrives -- stores no form values, so the editor showed empty Topic
    and Bootstrap servers fields for sources that were demonstrably working. The
    DDL is the definition; the stored values are only a convenience, so fall back
    to reading the definition itself.
    """
    stored = options_from_json(entry.options_json)
    if stored:
        return stored
    parsed = parse_options(entry.sql_text)
    parsed.pop("connector", None)  # implied by the entry, and emitted separately
    return parsed


def _out(entry: CatalogEntry, used_by: list[str] | None = None) -> CatalogEntryOut:
    return CatalogEntryOut(
        id=entry.id,
        name=entry.name,
        kind=entry.kind,
        connector=entry.connector,
        description=entry.description,
        sql_text=entry.sql_text,
        options=_options_of(entry),
        updated_at=entry.updated_at,
        used_by=used_by or [],
        columns=[ColumnOut(name=n, type=t) for n, t in columns_of(entry.sql_text)],
    )


def _users_of(db: Session, name: str) -> list[str]:
    out = []
    for job in db.query(Job).all():
        try:
            refs = json.loads(job.catalog_refs or "[]")
        except json.JSONDecodeError:
            continue
        if name in refs:
            out.append(job.name)
    return sorted(out)


def _render(body: CatalogEntryIn, registry: ConnectorRegistry) -> str:
    """Produces the DDL, either from the form values or from hand-written SQL."""
    if body.sql_text:
        return body.sql_text.strip()

    connector = registry.get(body.connector)
    if connector is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No connector named '{body.connector}'. Available: "
                f"{', '.join(c.connector for c in registry.all())}"
            ),
        )
    columns = [Column(name=c.name, sql_type=c.sqlType) for c in body.columns]
    if not columns:
        columns = [Column(name=c.name, sql_type=c.sql_type) for c in connector.columns]
    try:
        return build_create_table(body.name, connector, body.options, columns)
    except DdlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[CatalogEntryOut])
def list_entries(
    kind: str | None = None,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> list[CatalogEntryOut]:
    q = db.query(CatalogEntry)
    if kind:
        q = q.filter(CatalogEntry.kind == kind)
    return [_out(e, _users_of(db, e.name)) for e in q.order_by(CatalogEntry.name).all()]


@router.get("/{name}", response_model=CatalogEntryOut)
def get_entry(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> CatalogEntryOut:
    e = db.query(CatalogEntry).filter(CatalogEntry.name == name).one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail=f"No catalog entry named '{name}'")
    return _out(e, _users_of(db, name))


@router.post("", response_model=CatalogEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: CatalogEntryIn,
    principal: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    registry: ConnectorRegistry = Depends(get_registry),
) -> CatalogEntryOut:
    if db.query(CatalogEntry).filter(CatalogEntry.name == body.name).count():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A catalog entry named '{body.name}' already exists.",
        )

    entry = CatalogEntry(
        name=body.name,
        kind=body.kind,
        connector=body.connector,
        description=body.description,
        sql_text=_render(body, registry),
        options_json=options_to_json(body.options),
        created_by=principal.username,
    )
    db.add(entry)
    db.commit()
    return _out(entry)


@router.put("/{name}", response_model=CatalogEntryOut)
def update_entry(
    name: str,
    body: CatalogEntryIn,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    registry: ConnectorRegistry = Depends(get_registry),
) -> CatalogEntryOut:
    entry = db.query(CatalogEntry).filter(CatalogEntry.name == name).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No catalog entry named '{name}'")

    # Renaming would orphan every job referencing the old name.
    if body.name != name:
        raise HTTPException(
            status_code=400,
            detail="A catalog entry cannot be renamed; create a new one and repoint its jobs.",
        )

    entry.kind = body.kind
    entry.connector = body.connector
    entry.description = body.description
    entry.sql_text = _render(body, registry)
    entry.options_json = options_to_json(body.options or parse_options(entry.sql_text))
    db.commit()
    return _out(entry, _users_of(db, name))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_entry(
    name: str,
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
) -> None:
    entry = db.query(CatalogEntry).filter(CatalogEntry.name == name).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No catalog entry named '{name}'")

    users = _users_of(db, name)
    if users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{name}' is used by: {', '.join(users)}. Update those jobs first.",
        )
    db.delete(entry)
    db.commit()


@router.post("/{name}/check", response_model=list[WarningOut])
def check_entry(
    name: str,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
) -> list[WarningOut]:
    entry = db.query(CatalogEntry).filter(CatalogEntry.name == name).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No catalog entry named '{name}'")
    ws = check_catalog_entry(entry.sql_text, entry.kind, entry.connector)
    return [WarningOut(level=w.level, code=w.code, message=w.message) for w in ws]


@router.post("/{name}/sample", response_model=SampleOut)
async def sample_entry(
    name: str,
    limit: int = 5,
    start: str = "earliest",
    _: Principal = Depends(require_writer),
    db: Session = Depends(get_session),
    gateway: SqlGatewayClient = Depends(get_gateway),
    store: SecretStore = Depends(get_secret_store),
) -> SampleOut:
    """Reads a few real records, so a job can be written against what is there.

    Requires write access rather than read: this runs a query against live data
    and briefly occupies a slot on the cluster.
    """
    entry = db.query(CatalogEntry).filter(CatalogEntry.name == name).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No catalog entry named '{name}'")
    if entry.kind != "source":
        raise HTTPException(
            status_code=400,
            detail="Only sources can be sampled; a sink is somewhere records go.",
        )

    result = await sample_source(gateway, store, db, entry, limit=limit, start=start)
    return SampleOut(
        columns=result.columns,
        rows=result.rows,
        nested={
            column: [
                NestedFieldOut(name=f.name, type=f.type, example=f.example) for f in fields
            ]
            for column, fields in result.nested.items()
        },
        error=result.error,
    )
