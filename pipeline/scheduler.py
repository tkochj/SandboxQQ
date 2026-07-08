import logging
from typing import List

from pipeline.stage import Stage

logger = logging.getLogger(__name__)


class PipelineScheduler:
    def __init__(self, stages: List[Stage]):
        self.stages = stages

    async def execute(self, event):
        await self._execute_stages(event, 0)

    async def _execute_stages(self, event, index: int):
        if index >= len(self.stages):
            return
        stage = self.stages[index]
        try:
            async for _ in stage.process(event):
                await self._execute_stages(event, index + 1)
        except Exception as e:
            logger.error(f"Stage '{stage.name}' error: {e}")
            event.set_reply(f"处理出错: {e}")
