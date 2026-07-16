"""
auth.py — Secure login authentication for the LoopBack Dashboard.

Users are stored in users.json (gitignored — never commit it).
Passwords are hashed with PBKDF2-SHA256 + per-user random salt.
No external dependencies needed (uses Python's built-in hashlib).

Quickstart
----------
  # Create or update a user interactively:
  python auth.py

  # Or call programmatically in another script:
  from auth import add_user
  add_user("sara", "SecurePass123", name="Sara M.", role="agent")

Roles
-----
  admin  — can clear database, manage users (future)
  agent  — can triage, approve, reject events (standard access)
"""

import json
import hashlib
import secrets
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
USERS_FILE = Path(__file__).parent / "users.json"
_ITERATIONS = 260_000   # PBKDF2 iteration count (NIST recommendation 2023)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with PBKDF2-SHA256. Returns (hex_hash, salt)."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS
    )
    return dk.hex(), salt


def _verify_password(stored_hash: str, stored_salt: str, password: str) -> bool:
    """Constant-time password comparison (prevents timing attacks)."""
    computed, _ = _hash_password(password, stored_salt)
    return secrets.compare_digest(computed, stored_hash)


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------
def load_users() -> dict:
    """Load all users from users.json. Returns {} if file doesn't exist."""
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_users(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def add_user(username: str, password: str, name: str = "", role: str = "agent") -> None:
    """Create or update a user. Safe to call multiple times."""
    if not username or not password:
        raise ValueError("Username and password are required.")
    username = username.strip().lower()
    pw_hash, salt = _hash_password(password)
    users = load_users()
    users[username] = {
        "name": name.strip() or username.title(),
        "role": role.strip().lower(),
        "password_hash": pw_hash,
        "salt": salt,
    }
    _save_users(users)


def remove_user(username: str) -> bool:
    """Remove a user. Returns True if removed, False if not found."""
    users = load_users()
    username = username.strip().lower()
    if username not in users:
        return False
    del users[username]
    _save_users(users)
    return True


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def check_login(username: str, password: str) -> dict | None:
    """
    Validate credentials. Returns user info dict on success, None on failure.

    Returned dict: {"username": str, "name": str, "role": str}
    """
    if not username or not password:
        return None
    users = load_users()
    user = users.get(username.strip().lower())
    if not user:
        return None
    if _verify_password(user["password_hash"], user["salt"], password):
        return {
            "username": username.strip().lower(),
            "name":     user.get("name", username),
            "role":     user.get("role", "agent"),
        }
    return None


def users_exist() -> bool:
    """Returns True if at least one user account has been created.

    If no user accounts are found in users.json, automatically seed a default
    developer account (admin / admin123) for seamless out-of-the-box testing.
    """
    users = load_users()
    if not users:
        try:
            add_user("admin", "admin123", name="Administrator", role="admin")
            print("Auto-seeded default developer account: admin / admin123")
            return True
        except Exception:
            return False
    return True


# ---------------------------------------------------------------------------
# CLI — python auth.py to add/manage users
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print("━" * 42)
    print("  LoopBack — User Management CLI")
    print("━" * 42)

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        users = load_users()
        if not users:
            print("  No users found. Run `python auth.py` to add one.")
        else:
            print(f"  {'Username':<20} {'Name':<24} {'Role'}")
            print(f"  {'─'*20} {'─'*24} {'─'*10}")
            for uname, info in users.items():
                print(f"  {uname:<20} {info.get('name',''):<24} {info.get('role','agent')}")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        uname = sys.argv[2] if len(sys.argv) > 2 else input("Username to remove: ").strip()
        if remove_user(uname):
            print(f"  ✓ User '{uname}' removed.")
        else:
            print(f"  ✗ User '{uname}' not found.")
        sys.exit(0)

    print()
    print("  Commands: python auth.py         — add/update user")
    print("            python auth.py list    — list all users")
    print("            python auth.py remove  — remove a user")
    print()

    uname    = input("  Username   : ").strip()
    password = input("  Password   : ").strip()
    name     = input("  Display name (optional, press Enter to skip): ").strip()
    role     = input("  Role [admin/agent] (default: agent): ").strip() or "agent"

    if not uname or not password:
        print("  ✗ Username and password are required.")
        sys.exit(1)

    add_user(uname, password, name, role)
    print(f"\n  ✓ User '{uname}' saved to {USERS_FILE.name}")
    print(f"    Name: {name or uname.title()}, Role: {role}")
    print("\n  Run `python auth.py list` to see all users.")
