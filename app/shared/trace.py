from contextvars import ContextVar

trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id_ctx", default=None)


def set_trace_id(trace_id: str | None) -> None:
    trace_id_ctx.set(trace_id)


def get_trace_id() -> str | None:
    return trace_id_ctx.get()
