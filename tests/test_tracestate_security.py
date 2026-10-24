"""Regression coverage for GHSA-xcq7-p3pf-p88h on the inbound metadata path."""

import pytest
from fastmcp.telemetry import extract_trace_context
from opentelemetry import trace

TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


@pytest.mark.parametrize(("padding", "retained"), [(0, True), (8180, True), (8192, False)])
def test_inbound_tracestate_bound(padding: int, retained: bool) -> None:
    """Reject oversized metadata before parsing while preserving its parent span."""
    state = "vendor=value" + " " * padding
    context = extract_trace_context({"traceparent": TRACEPARENT, "tracestate": state})
    span = trace.get_current_span(context).get_span_context()
    assert span.is_valid
    assert span.trace_id == int(TRACEPARENT.split("-")[1], 16)
    assert dict(span.trace_state.items()) == ({"vendor": "value"} if retained else {})
