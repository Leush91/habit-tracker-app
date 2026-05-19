import os
import jwt
import httpx

# Importăm clasele FastAPI de care avem nevoie:
# - HTTPException pentru erori controlate (401, 403, 503)
# - status pentru coduri HTTP mai clare
# - Depends pentru dependency injection
# - Request ca să putem salva informații în request.state
from fastapi import HTTPException, status, Depends, Request

# HTTPBearer citește header-ul:
# Authorization: Bearer <token>
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Cream schema de security care obligă requestul să aibă Bearer token
security = HTTPBearer()

# Issuer-ul pe care backend-ul îl acceptă în token.
# Dacă nu există în env, folosim valoarea default pentru Keycloak-ul tău.
KEYCLOAK_ISSUER = os.getenv(
    "KEYCLOAK_ISSUER",
    "https://auth.local/realms/devops-lvlup"
)

# URL-ul de JWKS (cheile publice) folosit pentru validarea semnăturii JWT.
# Dacă nu există în env, folosim valoarea default.
KEYCLOAK_JWKS_URL = os.getenv(
    "KEYCLOAK_JWKS_URL",
    "http://10.96.88.49/realms/devops-lvlup/protocol/openid-connect/certs"
)

# Client ID-ul aplicației din Keycloak.
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "habit-tracker")


def get_signing_key(token: str):
    # Încercăm să luăm JWKS-ul din Keycloak.
    # Acolo sunt cheile publice cu care verificăm dacă tokenul a fost semnat corect.
    try:
        response = httpx.get(KEYCLOAK_JWKS_URL, timeout=5.0, follow_redirects=True)
        response.raise_for_status()
        jwks = response.json()

    # Dacă nu putem ajunge la Keycloak/JWKS, întoarcem 503.
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach Keycloak JWKS: {str(e)}"
        )

    # Dacă răspunsul nu este JSON valid, tot 503.
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak JWKS response was not valid JSON"
        )

    # Verificăm să existe cheia "keys" în payload-ul JWKS.
    if "keys" not in jwks:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak JWKS payload missing 'keys'"
        )

    # Citim header-ul JWT fără să validăm încă tokenul.
    # Aici vrem doar să aflăm "kid" = key id.
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header"
        )

    # Căutăm în JWKS cheia publică care are același "kid".
    for key in jwks["keys"]:
        if key.get("kid") == kid:
            # Transformăm JWK în cheie RSA folosită de PyJWT.
            return jwt.algorithms.RSAAlgorithm.from_jwk(key)

    # Dacă nu găsim nicio cheie potrivită, tokenul nu poate fi verificat.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to find matching signing key"
    )


def get_current_token_payload(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    # Extragem tokenul efectiv din header-ul Authorization.
    token = credentials.credentials

    try:
        # Luăm cheia publică potrivită pentru validare.
        signing_key = get_signing_key(token)

        # Validăm tokenul:
        # - semnătura
        # - issuer-ul
        # - algoritmul
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            options={"verify_aud": False},  # momentan nu verificăm aud
        )

        # Salvăm în request.state user-ul și rolurile,
        # ca să le putem folosi mai târziu în logs.
        request.state.user = payload.get("preferred_username")
        request.state.roles = payload.get("realm_access", {}).get("roles", [])

        # Returnăm payload-ul pentru RBAC și alte verificări.
        return payload

    # Dacă am ridicat deja noi un HTTPException, îl lăsăm să meargă mai departe.
    except HTTPException:
        raise

    # Dacă tokenul e expirat, întoarcem 401 clar.
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )

    # Orice altă problemă de JWT -> 401 invalid token.
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )


def require_roles(allowed_roles: list[str]):
    # Asta returnează o dependency function care verifică RBAC.
    def role_checker(payload: dict = Depends(get_current_token_payload)):
        # Luăm rolurile din token, din realm_access.roles.
        user_roles = payload.get("realm_access", {}).get("roles", [])

        # Dacă niciun rol permis nu este prezent, întoarcem 403 Forbidden.
        if not any(role in user_roles for role in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden"
            )

        # Dacă userul are rol bun, returnăm payload-ul.
        return payload

    return role_checker