from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    dev_login_enabled: bool = False

    database_url: str
    jwt_secret: str


settings = Settings()
