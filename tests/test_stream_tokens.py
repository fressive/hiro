from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from server.api.v1.endpoints.session import _stream_text_segments


def test_stream_text_segments_extracts_structured_text_blocks():
    segments = _stream_text_segments(
        [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "name": "log", "input": {}},
            {"type": "text_delta", "text": " world"},
        ]
    )

    assert segments == [("text", "hello"), ("text", " world")]


def test_stream_text_segments_extracts_thinking_blocks():
    segments = _stream_text_segments(
        [
            {"type": "thinking", "thinking": "checking"},
            {"type": "reasoning", "reasoning": " paths"},
        ]
    )

    assert segments == [("thinking", "checking"), ("thinking", " paths")]


def test_stream_text_segments_reads_message_chunk_content():
    chunk = ChatGenerationChunk(
        message=AIMessageChunk(content=[{"type": "text", "text": "streamed"}])
    )

    assert _stream_text_segments(chunk.message) == [("text", "streamed")]
