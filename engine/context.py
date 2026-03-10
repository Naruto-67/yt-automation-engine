# engine/context.py — Ghost Engine V13.0
import threading

class PipelineContext:
    """
    Thread-safe context manager for the Ghost Engine pipeline.
    Replaces the dangerous os.environ["CURRENT_CHANNEL_ID"] anti-pattern.
    """
    _local = threading.local()

    @classmethod
    def set_channel_id(cls, channel_id: str):
        cls._local.channel_id = channel_id

    @classmethod
    def get_channel_id(cls) -> str:
        return getattr(cls._local, 'channel_id', 'default_channel')

ctx = PipelineContext()
