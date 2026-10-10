import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.auth import Principal
from app.models import AiProvider, User
from app.routes.ai import get_provider
from app.schemas import AiProviderIn
from app.secrets import SecretStore


@pytest.mark.parametrize("header", ["Authorization", " X-API-Key ", "Cookie", "Proxy-Authorization"])
def test_credentials_cannot_be_saved_as_extra_headers(header):
    with pytest.raises(ValidationError, match="Use Authentication"):
        AiProviderIn(extra_headers={header: "synthetic-value"})


@pytest.mark.parametrize("role", ["viewer", "editor", "admin"])
def test_custom_headers_are_only_returned_to_admins(db, role):
    db.add(AiProvider(id=1, enabled=False, extra_headers='{"X-Project": "example"}'))
    db.commit()
    user = User(username="operator", role=role, password_hash="unused")
    result = get_provider(Principal(user=user, via="session"), db,
                          SecretStore(key=Fernet.generate_key()))
    assert result.extra_headers == ({"X-Project": "example"} if role == "admin" else {})
