from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl


class TaskItem(BaseModel):
    """A to-do item or task to be saved."""
    task: str = Field(description="The actual action item or task text")
    priority: Annotated[int, Field(ge=1, le=3)] | None = Field(
        default=None, description="1=High, 2=Medium, 3=Low"
    )


class ReadingLink(BaseModel):
    """A web link to an article, video, or resource to read later."""
    url: HttpUrl = Field(description="Valid URL of the resource")
    context: str | None = Field(default=None, description="Optional note about why to read this")
