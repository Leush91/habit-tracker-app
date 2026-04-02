import os
import jwt
import httpx

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", "http://auth.local/realms/devops-lvlup")
KEYCLOAK_JWKS_URL = os.getenv(
    "KEYCLOAK_JWKS_URL",
    "http://auth.local/realms/devops-lvlup/protocol/openid-connect/certs"
)
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "habit-tracker")


def get_signing_key(token: str):
    jwks = httpx.get(KEYCLOAK_JWKS_URL, timeout=5.0).json()
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    for key in jwks["keys"]:
        if key["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to find matching signing key"
    )


def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    try:
        signing_key = get_signing_key(token)

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            options={"verify_aud": False},
        )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
