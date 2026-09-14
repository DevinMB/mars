"""Execution targets decide which cluster a job is sent to.

Placement in Flink is not per-node: a session cluster's scheduler uses any free
slot, so choosing where a job runs means choosing which cluster receives it. These
tests cover the rules that keep that choice coherent."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Job, Target
from app.secrets import SecretStore
from app.targets import DEFAULT_TARGET, TargetRegistry, UnknownTargetError, labels_of
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _settings(monkeypatch, tmp_path):
    from app import settings as settings_mod
    settings_mod.settings.cache_clear()
    monkeypatch.setenv("MARS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARS_FLINK_REST_URL", "http://jobmanager:8081")
    monkeypatch.setenv("MARS_SQL_GATEWAY_URL", "http://sql-gateway:8083")
    yield
    settings_mod.settings.cache_clear()


@pytest.fixture
def registry():
    return TargetRegistry(SecretStore(key=Fernet.generate_key()))


def test_default_is_created_from_configuration(db, registry):
    """An upgrade must not leave existing jobs pointing at nothing."""
    t = registry.ensure_default(db)
    db.commit()
    assert t.name == DEFAULT_TARGET
    assert t.is_default
    assert t.flink_rest_url == "http://jobmanager:8081"
    assert t.gateway_url == "http://sql-gateway:8083"


def test_default_is_created_once(db, registry):
    a = registry.ensure_default(db); db.commit()
    b = registry.ensure_default(db); db.commit()
    assert a.id == b.id
    assert db.query(Target).count() == 1


def test_a_job_without_a_target_uses_the_default(db, registry):
    registry.ensure_default(db)
    job = Job(name="j", sql_text="SELECT 1", catalog_refs="[]", target_name=None)
    db.add(job); db.commit()
    assert registry.for_job(db, job).name == DEFAULT_TARGET


def test_a_job_can_name_another_target(db, registry):
    registry.ensure_default(db)
    db.add(Target(name="heavy", flink_rest_url="http://big:8081",
                  gateway_url="http://big:8083"))
    db.commit()
    job = Job(name="j", sql_text="SELECT 1", catalog_refs="[]", target_name="heavy")
    db.add(job); db.commit()
    assert registry.for_job(db, job).flink_rest_url == "http://big:8081"


def test_an_unknown_target_says_so_clearly(db, registry):
    registry.ensure_default(db); db.commit()
    job = Job(name="j", sql_text="SELECT 1", catalog_refs="[]", target_name="gone")
    with pytest.raises(UnknownTargetError, match="No execution target named 'gone'"):
        registry.for_job(db, job)


def test_a_disabled_target_refuses_work(db, registry):
    registry.ensure_default(db)
    db.add(Target(name="drained", flink_rest_url="http://x:8081",
                  gateway_url="http://x:8083", enabled=False))
    db.commit()
    job = Job(name="j", sql_text="SELECT 1", catalog_refs="[]", target_name="drained")
    with pytest.raises(UnknownTargetError, match="disabled"):
        registry.for_job(db, job)


def test_submitters_are_cached_per_target(db, registry):
    registry.ensure_default(db)
    db.add(Target(name="heavy", flink_rest_url="http://big:8081",
                  gateway_url="http://big:8083"))
    db.commit()
    default = registry.resolve(db, None)
    heavy = registry.resolve(db, "heavy")

    assert registry.submitter(default) is registry.submitter(default)
    assert registry.submitter(default) is not registry.submitter(heavy)


def test_editing_a_targets_url_rebuilds_its_clients(db, registry):
    """A corrected URL should take effect without restarting the console."""
    registry.ensure_default(db)
    t = db.scalar(select(Target).where(Target.name == DEFAULT_TARGET))
    first = registry.submitter(t)

    t.flink_rest_url = "http://moved:8081"
    db.commit()
    assert registry.submitter(t) is not first


def test_labels_survive_a_round_trip(db):
    t = Target(name="x", flink_rest_url="u", gateway_url="v",
               labels='{"zone":"rack-1","profile":"memory"}')
    assert labels_of(t) == {"zone": "rack-1", "profile": "memory"}


def test_malformed_labels_do_not_break_anything(db):
    assert labels_of(Target(name="x", flink_rest_url="u", gateway_url="v",
                            labels="not json")) == {}


def test_enabled_targets_are_listed_in_order(db, registry):
    registry.ensure_default(db)
    db.add(Target(name="beta", flink_rest_url="u", gateway_url="v"))
    db.add(Target(name="alpha", flink_rest_url="u", gateway_url="v"))
    db.add(Target(name="off", flink_rest_url="u", gateway_url="v", enabled=False))
    db.commit()
    assert [t.name for t in registry.all_enabled(db)] == ["alpha", "beta", "default"]


# -- reconcile must ask the right cluster ----------------------------------


@pytest.mark.asyncio
async def test_reconcile_only_touches_runs_on_its_own_target(db, registry):
    """The bug this guards: a job placed on a second cluster was reconciled
    against the default one, which had never heard of it, so a run that was
    finishing perfectly well got marked lost."""
    from app.cluster import JobOverview
    from app.models import JobRun, RunState
    from app.submitter import JobSubmitter

    registry.ensure_default(db)
    db.add(Target(name="secondary", flink_rest_url="http://b:8081", gateway_url="http://b:8083"))

    here = Job(name="here", sql_text="s", catalog_refs="[]", target_name=None)
    there = Job(name="there", sql_text="s", catalog_refs="[]", target_name="secondary")
    db.add_all([here, there])
    db.flush()
    db.add(JobRun(job_id=here.id, job_version=1, flink_job_id="a" * 32,
                  state=RunState.RUNNING.value))
    db.add(JobRun(job_id=there.id, job_version=1, flink_job_id="b" * 32,
                  state=RunState.RUNNING.value))
    db.commit()

    class FakeCluster:
        """Behaves like the default cluster: it knows only its own job."""
        def __init__(self, known):
            self.known = known
            self.asked = []

        async def list_jobs(self):
            return [JobOverview(job_id=j, name="x", state="RUNNING") for j in self.known]

    store = SecretStore(key=Fernet.generate_key())
    default_cluster = FakeCluster({"a" * 32})
    submitter = JobSubmitter(gateway=None, cluster=default_cluster, store=store)

    # Scoped to the default target: only the run placed there is considered, so the
    # secondary job is left alone rather than declared missing.
    await submitter.refresh_states(db, target_name=None)

    runs = {r.job_id: r.state for r in db.query(JobRun).all()}
    assert runs[here.id] == RunState.RUNNING.value
    assert runs[there.id] == RunState.RUNNING.value, (
        "a run on another target must not be marked lost by the default cluster"
    )


@pytest.mark.asyncio
async def test_unscoped_reconcile_still_works_for_one_cluster(db, registry):
    from app.cluster import JobOverview
    from app.models import JobRun, RunState
    from app.submitter import JobSubmitter

    registry.ensure_default(db)
    job = Job(name="j", sql_text="s", catalog_refs="[]", target_name=None)
    db.add(job); db.flush()
    db.add(JobRun(job_id=job.id, job_version=1, flink_job_id="c" * 32,
                  state=RunState.RUNNING.value))
    db.commit()

    class FakeCluster:
        async def list_jobs(self):
            return [JobOverview(job_id="c" * 32, name="x", state="FINISHED")]

    submitter = JobSubmitter(gateway=None, cluster=FakeCluster(),
                             store=SecretStore(key=Fernet.generate_key()))
    await submitter.refresh_states(db)
    assert db.query(JobRun).one().state == RunState.FINISHED.value


# -- who may change the fleet ----------------------------------------------


def test_target_writes_are_admin_only():
    """Pins the guards rather than trusting they stay put.

    A target decides where jobs run and what URL they are submitted to, so an
    editor being able to add one would let them redirect work to a cluster of their
    choosing. The probe is included because it makes the server fetch a URL the
    caller picked, which is a way to scan an internal network from inside it.
    """
    from app.deps import require_admin, current_principal
    from app.routes import targets as mod

    guards = {}
    for route in mod.router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        guards[(sorted(route.methods - {"HEAD", "OPTIONS"})[0], route.path)] = deps

    admin_only = [
        ("POST", "/api/targets"),
        ("PUT", "/api/targets/{name}"),
        ("DELETE", "/api/targets/{name}"),
        ("POST", "/api/targets/probe"),
    ]
    for key in admin_only:
        assert key in guards, f"{key} is missing from the router"
        assert require_admin in guards[key], f"{key[0]} {key[1]} must require an administrator"

    # Reading the fleet is fine for anyone signed in; the job list shows it anyway.
    listing = guards[("GET", "/api/targets")]
    assert current_principal in listing
    assert require_admin not in listing
