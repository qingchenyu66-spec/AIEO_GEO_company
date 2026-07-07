from typing import Literal

from pydantic import BaseModel, Field


class SentimentWordCloudItem(BaseModel):
    text: str
    count: int = Field(ge=1)
    subtask_id: str = ""
    task_id: str = ""


class SentimentWordCloudImageRequest(BaseModel):
    items: list[SentimentWordCloudItem] = Field(default_factory=list)
    polarity: Literal["positive", "negative"] = "positive"
    width: int = Field(default=900, ge=320, le=2400)
    height: int = Field(default=720, ge=260, le=1920)
    max_words: int = Field(default=120, ge=40, le=200)


class SentimentWordCloudPlacement(BaseModel):
    text: str
    count: int = 0
    subtask_id: str = ""
    task_id: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


class SentimentWordCloudImageResponse(BaseModel):
    image_base64: str = ""
    width: int = 900
    height: int = 720
    placements: list[SentimentWordCloudPlacement] = Field(default_factory=list)
