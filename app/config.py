from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./app.db"
    keitaro_base_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""
    keitaro_domain_name: str = "https://in.posdk.xyz/"
    keitaro_group_name: str = "FORTESTS"
    keitaro_source_name: str = "FORTESTS"


settings = Settings()
