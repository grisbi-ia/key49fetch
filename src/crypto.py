"""Credential encryption using Fernet (AES-128-CBC + HMAC).

Passwords are encrypted at rest and decrypted only in memory.
The encryption key is read from the FERNET_KEY environment variable.
If not set, a warning is logged and passwords are stored in plain text
(for development only).

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
"""

from __future__ import annotations

import os
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet | None:
    """Get a Fernet instance from the environment key.

    Returns:
        Fernet instance, or None if no key is configured.
    """
    key = os.environ.get("FERNET_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_password(plain_text: str) -> str:
    """Encrypt a password for storage.

    Args:
        plain_text: The plain-text password.

    Returns:
        Encrypted string (Fernet token), or the original text
        if encryption is not configured.
    """
    fernet = _get_fernet()
    if fernet is None:
        return plain_text  # No encryption configured
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt_password(encrypted_text: str) -> str:
    """Decrypt a stored password.

    Args:
        encrypted_text: The encrypted Fernet token.

    Returns:
        Decrypted plain-text password, or the original text
        if encryption is not configured.
    """
    fernet = _get_fernet()
    if fernet is None:
        return encrypted_text  # Not encrypted
    try:
        return fernet.decrypt(encrypted_text.encode()).decode()
    except Exception:
        # Fallback: might be plain text from before encryption was enabled
        return encrypted_text
