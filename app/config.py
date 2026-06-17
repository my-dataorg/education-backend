from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "education-backend"
    database_url: str = "postgresql+psycopg2://mydata:mydata@localhost:5433/education_db"
    cors_origins: str = "http://localhost:3010"
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "mydata"
    keycloak_admin_user: str = "admin"
    keycloak_admin_password: str = "admin"
    subscriptions_api_url: str = "http://localhost:8002"

    @property
    def jwks_url(self) -> str:
        return (
            f"{self.keycloak_url}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect/certs"
        )

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    class Config:
        env_file = ".env"


settings = Settings()
