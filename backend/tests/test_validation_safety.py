from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from app.drafting import draft_statement
from app.models import Job
from app.secrets import SecretStore
from app.submitter import JobSubmitter, SubmissionError


@pytest.mark.asyncio
async def test_validation_never_executes_leading_inserts(db):
    gateway = AsyncMock()
    submitter = JobSubmitter(gateway, AsyncMock(), SecretStore(key=Fernet.generate_key()))
    job = Job(name="example", catalog_refs="[]", sql_text="CREATE TABLE src (x INT); INSERT INTO out SELECT * FROM src; INSERT INTO out2 SELECT * FROM src")
    await submitter.validate(db, job)
    assert [call.args[1] for call in gateway.execute.call_args_list] == ["CREATE TABLE src (x INT)"]
    assert len(gateway.validate.call_args_list) == 2
    gateway.close_session.assert_awaited_once()


@pytest.mark.parametrize("statement", [
    "DROP TABLE important", "CREATE TABLE copied AS SELECT * FROM src",
    "CREATE TABLE copied AS ((SELECT * FROM src))", "ADD JAR 'https://example.test/code.jar'",
])
@pytest.mark.asyncio
async def test_unsafe_validation_is_rejected_before_gateway_contact(db, statement):
    gateway = AsyncMock()
    submitter = JobSubmitter(gateway, AsyncMock(), SecretStore(key=Fernet.generate_key()))
    job = Job(name="example", catalog_refs="[]", sql_text="CREATE TABLE src (x INT); " + statement)
    with pytest.raises(SubmissionError):
        await submitter.validate(db, job)
    gateway.open_session.assert_not_called()


@pytest.mark.asyncio
async def test_statement_set_is_explained_as_one_unit(db):
    gateway = AsyncMock()
    submitter = JobSubmitter(gateway, AsyncMock(), SecretStore(key=Fernet.generate_key()))
    sql = "EXECUTE STATEMENT SET BEGIN INSERT INTO a SELECT * FROM src; INSERT INTO b SELECT * FROM src; END"
    await submitter.validate(db, Job(name="example", catalog_refs="[]", sql_text=sql))
    gateway.execute.assert_not_called()
    gateway.validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_cannot_execute_setup_on_initial_or_repair_attempt():
    client = AsyncMock()
    client.complete.side_effect = [
        "INSERT INTO a SELECT * FROM src; INSERT INTO b SELECT * FROM src",
        "CREATE TEMPORARY FUNCTION surprise AS 'example.Code'",
    ]
    validate = AsyncMock(return_value=(True, None, None))
    result = await draft_statement(client, "draft a pipeline", [], "streaming", validate)
    assert not result.ok and result.attempts == 2
    validate.assert_not_called()


@pytest.mark.asyncio
async def test_single_model_insert_is_validated():
    client = AsyncMock()
    client.complete.return_value = "-- generated draft\nINSERT INTO out SELECT * FROM src;"
    validate = AsyncMock(return_value=(True, None, None))
    assert (await draft_statement(client, "draft", [], "streaming", validate)).ok
    validate.assert_awaited_once()
