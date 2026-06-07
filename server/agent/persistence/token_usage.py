"""Token usage extraction and normalization helpers."""

from typing import Any, Protocol


TOKEN_USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens")


class TokenUsageTarget(Protocol):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int


def usage_value(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        return data.get(key)
    return getattr(data, key, None)


def token_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    return 0


def first_token_count(data: Any, *keys: str) -> int:
    for key in keys:
        count = token_count(usage_value(data, key))
        if count:
            return count
    return 0


def nested_token_count(data: Any, *path: str) -> int:
    current = data
    for key in path:
        current = usage_value(current, key)
        if current is None:
            return 0
    return token_count(current)


def empty_token_usage() -> dict[str, int]:
    return {key: 0 for key in TOKEN_USAGE_KEYS}


def has_token_usage(usage: dict[str, int]) -> bool:
    return any(usage.get(key, 0) > 0 for key in TOKEN_USAGE_KEYS)


def add_token_usage(*usages: dict[str, int]) -> dict[str, int]:
    total = empty_token_usage()
    for usage in usages:
        for key in TOKEN_USAGE_KEYS:
            total[key] += usage.get(key, 0)
    return total


def subtract_token_usage(
    usage: dict[str, int], subtract: dict[str, int]
) -> dict[str, int]:
    return {
        key: max((usage.get(key, 0) or 0) - (subtract.get(key, 0) or 0), 0)
        for key in TOKEN_USAGE_KEYS
    }


def normalize_token_usage(usage: Any) -> dict[str, int]:
    """Normalize token usage metadata from LangChain and provider-specific APIs."""
    normalized = empty_token_usage()
    if not usage:
        return normalized

    input_tokens = first_token_count(usage, "input_tokens", "prompt_tokens")
    output_tokens = first_token_count(usage, "output_tokens", "completion_tokens")

    prompt_cache_hit_tokens = first_token_count(
        usage, "prompt_cache_hit_tokens", "cache_read_input_tokens"
    )
    prompt_cache_miss_tokens = first_token_count(usage, "prompt_cache_miss_tokens")
    if not input_tokens and (prompt_cache_hit_tokens or prompt_cache_miss_tokens):
        input_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens

    total_tokens = first_token_count(usage, "total_tokens")
    if total_tokens:
        if not input_tokens and output_tokens:
            input_tokens = max(total_tokens - output_tokens, 0)
        elif input_tokens and not output_tokens:
            output_tokens = max(total_tokens - input_tokens, 0)

    cached_input_tokens = first_token_count(
        usage,
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_read",
        "cached_tokens",
        "prompt_cache_hit_tokens",
    )
    if not cached_input_tokens:
        cached_input_tokens = (
            nested_token_count(usage, "input_token_details", "cache_read")
            or nested_token_count(usage, "input_token_details", "cached_tokens")
            or nested_token_count(usage, "input_tokens_details", "cache_read")
            or nested_token_count(usage, "input_tokens_details", "cached_tokens")
            or nested_token_count(usage, "prompt_token_details", "cached_tokens")
            or nested_token_count(usage, "prompt_tokens_details", "cached_tokens")
        )

    normalized["input_tokens"] = input_tokens
    normalized["output_tokens"] = output_tokens
    normalized["cached_input_tokens"] = cached_input_tokens
    return normalized


def best_token_usage(candidates: list[Any]) -> dict[str, int]:
    best = empty_token_usage()
    best_total = 0
    for candidate in candidates:
        usage = normalize_token_usage(candidate)
        total = sum(usage.values())
        if total > best_total:
            best = usage
            best_total = total
    return best


def metadata_usage_candidates(metadata: Any) -> list[Any]:
    if not metadata:
        return []
    return [
        usage_value(metadata, "token_usage"),
        usage_value(metadata, "usage"),
        usage_value(metadata, "usage_metadata"),
    ]


def message_token_usage(message: Any) -> dict[str, int]:
    response_metadata = getattr(message, "response_metadata", None)
    additional_kwargs = getattr(message, "additional_kwargs", None)
    candidates = [
        getattr(message, "usage_metadata", None),
        *metadata_usage_candidates(response_metadata),
        *metadata_usage_candidates(additional_kwargs),
    ]
    return best_token_usage(candidates)


def llm_result_token_usage(response: Any) -> dict[str, int]:
    if not response:
        return empty_token_usage()

    llm_output = getattr(response, "llm_output", None)
    top_level_usage = best_token_usage(
        [
            usage_value(llm_output, "token_usage"),
            *metadata_usage_candidates(usage_value(llm_output, "metadata")),
            usage_value(llm_output, "usage"),
            usage_value(llm_output, "usage_metadata"),
        ]
    )

    generation_usages = []
    for generations in getattr(response, "generations", []) or []:
        for generation in generations:
            generation_usage = best_token_usage(
                [
                    message_token_usage(getattr(generation, "message", None)),
                    *metadata_usage_candidates(
                        getattr(generation, "generation_info", None)
                    ),
                ]
            )
            if has_token_usage(generation_usage):
                generation_usages.append(generation_usage)

    generation_usage = add_token_usage(*generation_usages)
    if not has_token_usage(top_level_usage):
        return generation_usage
    if not has_token_usage(generation_usage):
        return top_level_usage
    return {
        key: max(top_level_usage.get(key, 0), generation_usage.get(key, 0))
        for key in TOKEN_USAGE_KEYS
    }


def apply_token_usage(message: TokenUsageTarget, usage: dict[str, int]) -> None:
    if not has_token_usage(usage):
        return
    message.input_tokens = usage["input_tokens"]
    message.output_tokens = usage["output_tokens"]
    message.cached_input_tokens = usage["cached_input_tokens"]


__all__ = [
    "TOKEN_USAGE_KEYS",
    "TokenUsageTarget",
    "add_token_usage",
    "apply_token_usage",
    "best_token_usage",
    "empty_token_usage",
    "first_token_count",
    "has_token_usage",
    "llm_result_token_usage",
    "message_token_usage",
    "metadata_usage_candidates",
    "nested_token_count",
    "normalize_token_usage",
    "subtract_token_usage",
    "token_count",
    "usage_value",
]
