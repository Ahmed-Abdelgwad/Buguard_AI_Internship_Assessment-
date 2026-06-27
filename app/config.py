from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/darkatlas"

    # Auth — two roles: admin (full access) and reader (read-only + AI analysis)
    api_key: str = "changeme"          # admin key (backward-compatible)
    reader_api_key: str = "readonly"   # reader key

    # Anthropic / LangChain
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    # Cache
    cache_ttl: int = 600  # seconds
    cache_maxsize: int = 512

    # Pagination defaults
    default_page_size: int = 20
    max_page_size: int = 100


settings = Settings()
