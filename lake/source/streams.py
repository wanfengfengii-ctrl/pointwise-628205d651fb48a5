from dataclasses import dataclass

from lake.source.store import SourceStore


@dataclass(frozen=True)
class StreamHead:
    stream: str
    revision_id: str
    ordinal: int


def read_stream_head(store: SourceStore, stream: str) -> StreamHead | None:
    found = store.load_head(stream)
    if found is None:
        return None
    return StreamHead(stream, found['revision_id'], found['ordinal'])


def require_predecessor(head: StreamHead | None, predecessor: str | None) -> int:
    if head is None:
        if predecessor is not None:
            raise ValueError('first revision requires an empty predecessor')
        return 1
    if predecessor != head.revision_id:
        raise ValueError('predecessor must match the current stream head')
    return head.ordinal + 1
