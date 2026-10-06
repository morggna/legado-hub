"""One-time/multi-use registration invitations. Raw codes are returned only once."""
import hashlib
import secrets
import sqlite3
import time
import uuid

from fastapi import HTTPException

from app.services.user_auth import auth_service


class InvitationService:
    def __init__(self, auth=None):
        self._auth = auth

    @property
    def auth(self):
        return self._auth or auth_service

    @staticmethod
    def digest(code):
        return hashlib.sha256(code.strip().encode()).hexdigest()

    def create(self, admin_id, max_uses=1, expires_days=7):
        code = secrets.token_urlsafe(24)
        invitation_id = uuid.uuid4().hex
        expires = int(time.time()) + expires_days * 86400
        with self.auth._conn() as conn:
            conn.execute("INSERT INTO registration_invites(invite_id,code_hash,label,max_uses,expires_at,created_by) VALUES(?,?,?,?,?,?)",
                         (invitation_id, self.digest(code), code[-6:], max_uses, expires, admin_id))
            conn.commit()
        return {"inviteId": invitation_id, "code": code, "maxUses": max_uses, "expiresAt": expires}

    def list(self):
        with self.auth._conn() as conn:
            rows = conn.execute("SELECT invite_id,label,max_uses,used_count,expires_at,revoked FROM registration_invites ORDER BY created_at DESC").fetchall()
        return [{"inviteId": r[0], "label": r[1], "maxUses": r[2], "usedCount": r[3], "expiresAt": r[4], "revoked": bool(r[5])} for r in rows]

    def revoke(self, invitation_id):
        with self.auth._conn() as conn:
            cursor = conn.execute("UPDATE registration_invites SET revoked=1 WHERE invite_id=?", (invitation_id,))
            if not cursor.rowcount:
                raise HTTPException(404, "邀请码不存在")
            conn.commit()

    def register(self, username, password, code):
        username = self.auth._validate_username(username)
        password = self.auth._validate_password(password)
        password_hash = self.auth.hash_password(password)
        user_id = uuid.uuid4().hex
        now = self.auth._now()
        try:
            with self.auth._conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT invite_id,max_uses,used_count,expires_at,revoked FROM registration_invites WHERE code_hash=?", (self.digest(code),)).fetchone()
                if not row or row[4] or row[3] <= int(time.time()) or row[2] >= row[1]:
                    raise HTTPException(400, "邀请码无效、已过期或已用完")
                conn.execute("INSERT INTO users(user_id,username,password_hash,role,disabled,created_at,updated_at) VALUES(?,?,?,'user',0,?,?)",
                             (user_id, username, password_hash, now, now))
                conn.execute("UPDATE registration_invites SET used_count=used_count+1 WHERE invite_id=?", (row[0],))
                conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名已存在") from None
        return self.auth.get_user(user_id)


invitation_service = InvitationService()
