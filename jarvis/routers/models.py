from pydantic import BaseModel
from typing import Optional

class TaskRequest(BaseModel):
    prompt: str
    working_dir: str = "."

class PCCommandRequest(BaseModel):
    text: str

class GoogleConfigRequest(BaseModel):
    config: dict
    services: list[str]

class GoogleConnectRequest(BaseModel):
    services: Optional[list[str]] = None

class GoogleAPIKeyRequest(BaseModel):
    key: str

class OpenAppRequest(BaseModel):
    name: str

class KeyUpdate(BaseModel):
    key_name: str
    key_value: str

class KeyTest(BaseModel):
    key_value: str | None = None

class PreferencesUpdate(BaseModel):
    user_name: str = ""
    honorific: str = "sir"
    stt_keywords: str = ""
