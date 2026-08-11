from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    dev_login_enabled: bool = False

    database_url: str
    jwt_secret: str

    apple_bundle_id: str = ""
    google_client_ids: str = ""

    @property
    def google_audiences(self) -> list[str]:
        return [c.strip() for c in self.google_client_ids.split(",") if c.strip()]


settings = Settings()

