"""Cluster status and the connector catalogue."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import Principal
from ..db import get_session
from .. import updates
from ..deps import current_principal, get_registry, get_targets, require_admin
from ..registry import ConnectorRegistry
from ..schemas import ClusterOut
from ..settings import settings
from ..targets import TargetRegistry

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/cluster", response_model=ClusterOut)
async def cluster_status(
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_session),
    registry: TargetRegistry = Depends(get_targets),
) -> ClusterOut:
    """Capacity across every execution target, not just the default one.

    This used to read the configured cluster directly, which was right when there
    was only ever one. Once jobs can be placed on other targets, reporting the
    default's slots as though they were all of them understates the fleet -- the
    header read 3/12 with a second cluster registered and idle.
    """
    registry.ensure_default(db)
    db.commit()
    targets = registry.all_enabled(db)

    async def probe(t):
        try:
            return await registry.cluster(t).info()
        except Exception:
            return None

    infos = [i for i in await asyncio.gather(*(probe(t) for t in targets)) if i is not None]
    if not infos:
        return ClusterOut(reachable=False, targets_total=len(targets), targets_reachable=0)

    return ClusterOut(
        reachable=True,
        # Versions can differ across targets mid-upgrade; report one only when they agree.
        flink_version=infos[0].flink_version
        if len({i.flink_version for i in infos}) == 1
        else "mixed",
        taskmanagers=sum(i.taskmanagers for i in infos),
        slots_total=sum(i.slots_total for i in infos),
        slots_available=sum(i.slots_available for i in infos),
        jobs_running=sum(i.jobs_running for i in infos),
        targets_total=len(targets),
        targets_reachable=len(infos),
    )


@router.get("/connectors")
def list_connectors(
    kind: str | None = None,
    _: Principal = Depends(current_principal),
    registry: ConnectorRegistry = Depends(get_registry),
) -> list[dict]:
    """The manifests the console builds its source and sink forms from."""
    connectors = registry.for_kind(kind) if kind else registry.all()
    return [c.to_json() for c in connectors]


@router.get("/connectors/{identifier}")
def get_connector(
    identifier: str,
    _: Principal = Depends(current_principal),
    registry: ConnectorRegistry = Depends(get_registry),
) -> dict:
    from fastapi import HTTPException

    c = registry.get(identifier)
    if c is None:
        raise HTTPException(status_code=404, detail=f"No connector named '{identifier}'")
    return c.to_json()


# --- versions and updates ----------------------------------------------------


def _image_repo(image: str) -> str:
    """ghcr.io/x/mars-console@sha256:... or :tag -> ghcr.io/x/mars-console."""
    name = image.split("@", 1)[0]
    head, _, tail = name.rpartition("/")
    return f"{head}/{tail.split(':', 1)[0]}" if head else tail.split(":", 1)[0]


def _how_to_update(component: str, commit: str) -> dict:
    """The steps for one component, from MARS_UPDATE_INSTRUCTIONS or generic ones.

    The console never runs these. Flink always needs a maintenance window: its
    jobs stop while the cluster is replaced, which the console cannot do for you.
    """
    s = settings()
    window = component == "flink"
    if s.update_instructions:
        command = s.update_instructions.format(component=component, commit=commit, short=commit[:7])
        return {"needs_window": window, "steps": [f"Run: {command}"], "command": command}

    image = s.console_image if component == "console" else s.flink_image
    repo = _image_repo(image) if image else f"ghcr.io/devinmb/mars-{component}"
    pin = "MARS_CONSOLE_IMAGE" if component == "console" else "MARS_FLINK_IMAGE"
    ref = f"{repo}:sha-{commit}"
    if not window:
        steps = [
            f"docker pull {ref}",
            f"Set {pin} in .env to the digest that prints (docker image inspect --format "
            "'{{index .RepoDigests 0}}' " + ref + ")",
            "docker compose up -d --no-deps console",
        ]
    else:
        steps = [
            "Plan a short maintenance window: every job on this cluster stops while it is replaced.",
            "In MARS, stop each running job with Stop and save state.",
            f"docker pull {ref}, and set {pin} in .env to its digest.",
            "docker compose up -d --no-deps jobmanager taskmanager sql-gateway",
            "In MARS, resume each job. It continues from the state saved above.",
        ]
    return {"needs_window": window, "steps": steps, "command": None}


@router.get("/system/version")
def version(_: Principal = Depends(current_principal)) -> dict:
    """What this installation runs, and what the last update check found."""
    s = settings()
    last = updates.last_result() if s.update_check else None
    out = {
        "console": {"revision": s.revision or None, "built_at": s.built_at or None,
                    "image": s.console_image or None},
        "flink": {"revision": s.flink_revision or None, "image": s.flink_image or None},
        "update_check": {"enabled": s.update_check, "channel": s.update_channel,
                         "checked_at": last.checked_at if last else None,
                         "error": last.error if last else None},
        "latest": last.latest.__dict__ if last and last.latest else None,
    }
    for name in ("console", "flink"):
        status = getattr(last, name) if last else None
        if status is not None:
            out[name].update(
                behind_by=status.behind_by,
                update_available=status.update_available,
                commits=[c.__dict__ for c in status.commits],
                how_to_update=(_how_to_update(name, last.latest.revision)
                               if status.update_available and last.latest else None),
            )
    return out


@router.post("/system/version/check")
async def check_now(_: Principal = Depends(require_admin)) -> dict:
    """Checks for updates now, if checking is enabled."""
    if not settings().update_check:
        raise HTTPException(status_code=409, detail="Update checks are off. Set MARS_UPDATE_CHECK=true to turn them on.")
    await updates.check()
    return version(_)
