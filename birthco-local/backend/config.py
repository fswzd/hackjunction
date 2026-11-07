"""Local-only configuration, loaded when the Flask app is created."""
from dataclasses import dataclass
import os
from pathlib import Path
import secrets


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    data_dir: Path
    model_mode: str

    @classmethod
    def load(cls, overrides: dict | None = None):
        values = {
            "host": os.environ.get("BIRTHCO_HOST", "127.0.0.1"),
            "port": int(os.environ.get("BIRTHCO_PORT", "5000")),
            "data_dir": Path(os.environ.get("BIRTHCO_DATA_DIR") or Path(__file__).resolve().parents[1] / "data"),
            "model_mode": os.environ.get("BIRTHCO_MODEL_MODE", "mock"),
        }
        values.update(overrides or {})
        if values["host"] != "127.0.0.1" or values["port"] != 5000:
            raise ValueError("Local service must bind 127.0.0.1:5000")
        if values["model_mode"] not in {"mock", "live"}:
            raise ValueError("BIRTHCO_MODEL_MODE must be mock or live")
        values["data_dir"] = Path(values["data_dir"]).resolve()
        return cls(**values)


def session_secret(data_dir: Path) -> bytes:
    supplied = os.environ.get("BIRTHCO_SESSION_SECRET")
    if supplied is not None:
        if not supplied.strip() or len(supplied) < 32:
            raise ValueError("BIRTHCO_SESSION_SECRET is too short")
        return supplied.encode("utf-8")
    path = data_dir / "session.key"
    try:
        with path.open("xb") as output:
            output.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    secret = path.read_bytes()
    if len(secret) != 32:
        raise ValueError("Session secret file is invalid")
    return secret
