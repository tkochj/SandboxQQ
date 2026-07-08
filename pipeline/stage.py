from abc import ABC, abstractmethod
from typing import AsyncGenerator


class Stage(ABC):
    name: str = ""

    @abstractmethod
    async def process(self, event) -> AsyncGenerator[None, None]:
        yield
