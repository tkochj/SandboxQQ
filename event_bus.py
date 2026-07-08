import asyncio
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None
        self._running = False
        self._pipeline = None
        self._on_dispatch: Optional[Callable] = None

    def set_pipeline(self, pipeline):
        self._pipeline = pipeline

    def on_dispatch(self, callback: Callable):
        self._on_dispatch = callback

    def start(self):
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("EventBus started")

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._dispatch_loop())
        except RuntimeError:
            pass
        except Exception as e:
            logger.error(f"EventBus dispatch error: {e}")
        finally:
            self._loop.close()

    async def _dispatch_loop(self):
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"EventBus get error: {e}")
                continue
            if self._pipeline:
                asyncio.create_task(self._pipeline.execute(event))
            if self._on_dispatch:
                try:
                    if asyncio.iscoroutinefunction(self._on_dispatch):
                        await self._on_dispatch(event)
                    else:
                        self._on_dispatch(event)
                except Exception as e:
                    logger.error(f"Dispatch callback error: {e}")

    def publish(self, event):
        if self._loop and not self._loop.is_closed() and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
            logger.info(f"EventBus published: platform={event.platform_name} type={event.msg_type} content={event.content[:50]}")
        else:
            logger.warning(f"EventBus NOT STARTED, event dropped: {event.content[:50]}")

    def stop(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("EventBus stopped")
