from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from server.agent.persistence.token_usage import (
    add_token_usage,
    llm_result_token_usage,
    message_token_usage,
    normalize_token_usage,
    subtract_token_usage,
)
from server.agent.events.streaming import stream_text_segments


def test_stream_text_segments_extracts_structured_text_blocks():
    segments = stream_text_segments(
        [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "name": "log", "input": {}},
            {"type": "text_delta", "text": " world"},
        ]
    )

    assert segments == [("text", "hello"), ("text", " world")]


def test_stream_text_segments_extracts_thinking_blocks():
    segments = stream_text_segments(
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

    assert stream_text_segments(chunk.message) == [("text", "streamed")]


def test_normalize_token_usage_reads_openai_cached_prompt_tokens():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 75},
    }

    assert normalize_token_usage(usage) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_input_tokens": 75,
    }


def test_message_token_usage_reads_langchain_nested_cache_metadata():
    message = SimpleNamespace(
        usage_metadata={
            "input_tokens": 90,
            "output_tokens": 10,
            "input_token_details": {"cache_read": 30},
        },
        response_metadata={},
        additional_kwargs={},
    )

    assert message_token_usage(message) == {
        "input_tokens": 90,
        "output_tokens": 10,
        "cached_input_tokens": 30,
    }


def test_llm_result_token_usage_merges_cache_without_double_counting():
    message = SimpleNamespace(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 20,
            "input_token_details": {"cache_read": 50},
        },
        response_metadata={},
        additional_kwargs={},
    )
    response = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 20}},
        generations=[[SimpleNamespace(message=message, generation_info=None)]],
    )

    assert llm_result_token_usage(response) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_input_tokens": 50,
    }


def test_callback_residual_usage_avoids_recounting_message_usage():
    callback_usage = {"input_tokens": 100, "output_tokens": 40, "cached_input_tokens": 10}
    first_message_usage = {"input_tokens": 60, "output_tokens": 25, "cached_input_tokens": 8}
    second_message_usage = {"input_tokens": 10, "output_tokens": 10, "cached_input_tokens": 2}

    residual = subtract_token_usage(
        callback_usage, add_token_usage(first_message_usage, second_message_usage)
    )

    assert add_token_usage(
        add_token_usage(first_message_usage, residual), second_message_usage
    ) == callback_usage
