from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    dev_login_enabled: bool = False

    database_url: str
    jwt_secret: str

    apple_bundle_id: str = ""
    google_client_ids: str = ""

    # Sign in with Apple server credentials — needed only for token
    # *revocation* (account deletion, App Store guideline 5.1.1(v)), not for
    # login (login verifies identity tokens against Apple's public JWKS).
    # From the developer portal: the team id, a "Sign in with Apple" key's id,
    # and that key's .p8 contents (newlines may be escaped as \n in the env).
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""

    @property
    def apple_revocation_configured(self) -> bool:
        return bool(self.apple_team_id and self.apple_key_id and self.apple_private_key)

    @property
    def google_audiences(self) -> list[str]:
        return [c.strip() for c in self.google_client_ids.split(",") if c.strip()]


settings = Settings()

