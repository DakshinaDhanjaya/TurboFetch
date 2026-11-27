import hmac
import secrets


class PairingManager:
    def __init__(self, token: str = "", host: str = "127.0.0.1", port: int = 29512) -> None:
        self._token = token or self.generate_token()
        self._host = host
        self._port = port
        self.paired_extensions: set[str] = set()

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str) -> None:
        self._token = token

    def generate_token(self) -> str:
        self._token = secrets.token_hex(16)
        return self._token

    def verify_token(self, token: str) -> bool:
        if not token or not self._token:
            return False
        return hmac.compare_digest(token.strip(), self._token)

    def pair_extension(self, extension_id: str, provided_token: str) -> bool:
        if not extension_id or not self.verify_token(provided_token):
            return False
        self.paired_extensions.add(extension_id.strip())
        return True

    def get_pairing_url(self) -> str:
        return f"http://{self._host}:{self._port}/api/pairing"
