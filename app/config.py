from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "education-backend"
    database_url: str = "postgresql+psycopg2://mydata:mydata@localhost:5433/education_db"
    cors_origins: str = "http://localhost:3010"
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "mydata"
    keycloak_admin_user: str = "admin"
    keycloak_admin_password: str = "admin"
    subscriptions_api_url: str = "http://127.0.0.1:8002"
    social_api_url: str = ""
    platform_internal_token: str = "mydata-internal-dev-token"
    auth_issuer: str = "http://localhost:8002/v1/auth"
    # Comma-separated extra JWT iss values (same keys as auth_issuer).
    auth_issuer_aliases: str = ""
    use_platform_auth: bool = True
    assignment_llm_rewrite_enabled: bool = False

    def trusted_issuers(self) -> set[str]:
        issuers = {self.issuer}
        for part in self.auth_issuer_aliases.split(","):
            value = part.strip()
            if value:
                issuers.add(value)
        if self.use_platform_auth:
            # Docker vs host restarts often disagree on hostname while sharing one keypair.
            issuers.add("http://localhost:8002/v1/auth")
            issuers.add("http://platform-backend:8002/v1/auth")
        return issuers

    @property
    def jwks_url(self) -> str:
        if self.use_platform_auth:
            return f"{self.auth_issuer.rstrip('/')}/jwks"
        return (
            f"{self.keycloak_url}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect/certs"
        )

    @property
    def issuer(self) -> str:
        if self.use_platform_auth:
            return self.auth_issuer
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    class Config:
        env_file = ".env"


settings = Settings()
