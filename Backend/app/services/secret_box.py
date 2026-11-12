import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from app.conf.config import CREDENTIAL_KEY_PATH


class SecretBox:
    """Encrypts SSH credentials at rest with a key generated on first run."""

    def __init__(self, key_path: Path = CREDENTIAL_KEY_PATH) -> None:
        self._fernet = Fernet(_load_or_create_key(key_path))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        # Exclusive creation keeps two starting processes from writing different keys.
        with path.open("xb") as handle:
            handle.write(key)
    except FileExistsError:
        return path.read_bytes().strip()
    if os.name != "nt":
        os.chmod(path, 0o600)
    return key


@lru_cache(maxsize=1)
def get_secret_box() -> SecretBox:
    return SecretBox()
