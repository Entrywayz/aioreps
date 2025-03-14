from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
import os

class Settings(BaseSettings):
    bot_token: SecretStr
    db_path: SecretStr
    admin_id1: SecretStr
    admin_id2: SecretStr
    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), ".env"),
        env_file_encoding="utf-8"
    )
    
config = Settings()
