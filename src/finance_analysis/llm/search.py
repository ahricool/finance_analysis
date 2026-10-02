"""Transport evidence, deliberately independent of model-written source lists."""


def supported(config):
    if config.backend == "cli":
        return config.cli_engine == "codex"
    return config.api_search_mode == "chat_completions"


def evidence(requested, configured, citations=None, events=None):
    citations, events = citations or [], events or []
    return dict(
        requested=requested,
        configured_support=configured,
        status=(
            "confirmed"
            if requested and (citations or events)
            else "unverified" if requested and configured else "unavailable" if requested else "not_requested"
        ),
        citations=citations,
        tool_events=events,
    )
