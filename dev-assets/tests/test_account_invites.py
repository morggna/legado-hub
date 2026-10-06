from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api import auth, accounts, console, direct
from app.main import create_app
from app.services.invitations import InvitationService
from app.services.user_auth import UserAuthService


@pytest.fixture
def account_env(tmp_path, monkeypatch):
    original_admin_dependency = console.auth_service.require_admin
    original_user_dependency = console.auth_service.require_user
    service = UserAuthService(tmp_path / "accounts.db")
    service.bootstrap_admin("admin", "admin-password")
    invitations = InvitationService(service)
    monkeypatch.setattr(auth, "auth_service", service)
    monkeypatch.setattr(accounts, "auth_service", service)
    monkeypatch.setattr(accounts, "invitation_service", invitations)
    monkeypatch.setattr(console, "auth_service", service)
    monkeypatch.setattr(direct, "auth_service", service)
    app = create_app(auth_mode="account_invite", manage_runtime=False)
    app.dependency_overrides[original_admin_dependency] = service.require_admin
    app.dependency_overrides[original_user_dependency] = service.require_user
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin-password"}).status_code == 200
    return client, service, invitations


def test_registration_password_login_and_removed_authorization_code(account_env):
    admin, service, _ = account_env
    issued = admin.post("/api/accounts/invitations", json={"maxUses": 1, "expiresDays": 7})
    assert issued.status_code == 200
    code = issued.json()["code"]
    reader = TestClient(admin.app)
    assert reader.get("/api/direct/shelf").status_code == 401
    response = reader.post("/api/auth/register", json={"username": "new-reader", "password": "reader-password", "invitationCode": code})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"
    assert reader.get("/api/direct/sources").status_code == 200
    assert reader.post("/api/accounts/invitations", json={}).status_code == 403
    assert reader.get("/api/console/users").status_code == 403
    assert reader.post("/api/auth/access/redeem", json={"accessCode": code}).status_code == 404
    assert admin.post("/api/console/users/anything/reset-access-code", json={}).status_code == 410
    assert reader.post("/api/auth/logout").status_code == 200
    assert reader.post("/api/auth/login", json={"username": "new-reader", "password": "reader-password"}).status_code == 200
    assert reader.post("/api/auth/register", json={"username": "another", "password": "reader-password", "invitationCode": code}).status_code == 400
    assert service.get_user_by_username("another") is None
    assert code not in str(admin.get("/api/accounts/invitations").json())


def test_expired_revoked_and_forged_invites(account_env):
    admin, service, invitations = account_env
    uid = service.get_user_by_username("admin")["userId"]
    expired = invitations.create(uid)
    with service._conn() as conn:
        conn.execute("UPDATE registration_invites SET expires_at=0 WHERE invite_id=?", (expired["inviteId"],))
        conn.commit()
    revoked = invitations.create(uid)
    invitations.revoke(revoked["inviteId"])
    for code in [expired["code"], revoked["code"], "invalid"]:
        with pytest.raises(HTTPException):
            invitations.register("new", "reader-password", code)
    assert service.user_count() == 1
    response = TestClient(admin.app).post("/api/auth/register", json={"username": "new", "password": "reader-password", "invitationCode": "wrong", "role": "admin"})
    assert response.status_code == 422


def test_invite_consumption_is_atomic_under_concurrent_registration(account_env):
    _, service, invitations = account_env
    code = invitations.create(service.get_user_by_username("admin")["userId"])["code"]
    def register(name):
        try:
            return invitations.register(name, "reader-password", code)
        except HTTPException:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, ["first", "second"]))
    assert sum(r is not None for r in results) == 1
    assert invitations.list()[0]["usedCount"] == 1


def test_duplicate_username_does_not_consume_invitation_and_password_reset_revokes_sessions(account_env):
    admin, service, invitations = account_env
    code = invitations.create(service.get_user_by_username("admin")["userId"])["code"]
    with pytest.raises(HTTPException):
        invitations.register("admin", "reader-password", code)
    assert invitations.list()[0]["usedCount"] == 0
    user = invitations.register("reader", "reader-password", code)
    reader = TestClient(admin.app)
    assert reader.post("/api/auth/login", json={"username": "reader", "password": "reader-password"}).status_code == 200
    assert admin.post(f"/api/console/users/{user.user_id}/reset-password", json={"password": "new-password"}).status_code == 200
    assert reader.get("/api/direct/sources").status_code == 401
    assert reader.post("/api/auth/login", json={"username": "reader", "password": "new-password"}).status_code == 200
    response = admin.post("/api/console/users", json={"username": "managed", "password": "managed-password", "role": "user"})
    assert response.status_code == 200
    assert "accessCode" not in response.json()
