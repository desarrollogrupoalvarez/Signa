"""
JWT helpers.

This project expects the **PyJWT** library (pip package `PyJWT`, imported as `jwt`).
If a different `jwt` package is installed (e.g. `jwt==1.x`), it won't provide
`encode/decode` and login will fail with a 500.
"""

import jwt

from config import Config


def create_token(payload: dict) -> str:
    """Creates a JWT with no expiration (as configured)."""
    if not hasattr(jwt, "encode"):
        raise RuntimeError(
            "Dependencia JWT incorrecta: instalá PyJWT (pip install PyJWT) "
            "y desinstalá el paquete 'jwt' (pip uninstall jwt)."
        )
    return jwt.encode(payload, Config.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Decodes and verifies signature. Raises jwt.InvalidTokenError on failure."""
    if not hasattr(jwt, "decode"):
        raise RuntimeError(
            "Dependencia JWT incorrecta: instalá PyJWT (pip install PyJWT) "
            "y desinstalá el paquete 'jwt' (pip uninstall jwt)."
        )
    return jwt.decode(
        token,
        Config.JWT_SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False},  # no expiration enforced
    )
