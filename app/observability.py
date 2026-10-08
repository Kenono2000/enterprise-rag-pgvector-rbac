"""
app/observability.py
--------------------
Enterprise Observability and Tracing module.
Tracks retrieval latency, candidate counts, token usage, and retrieval precision.
Integrates with OpenTelemetry when configured, with structured metrics fallback.
"""

from __future__ import annotations

import time
import logging
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

logger = logging.getLogger("enterprise_rag.observability")


class ObservabilityTracer:
    """
    Centralized observability tracer for Enterprise RAG.
    Records structured execution metrics, latency, and token consumption.
    Integrates directly with OpenTelemetry (OTel) when enabled, with structured metrics fallback.
    """

    def __init__(self, service_name: str = "enterprise-rag-pgvector-rbac"):
        self.service_name = service_name
        self._metrics: List[Dict[str, Any]] = []
        self._otel_tracer = None
        
        # Check if OpenTelemetry is configured and installed
        import os
        if os.getenv("OTEL_ENABLED", "false").lower() == "true":
            try:
                from opentelemetry import trace
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.resources import Resource

                resource = Resource.create({"service.name": self.service_name})
                provider = TracerProvider(resource=resource)

                endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
                insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true"
                otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)

                provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
                trace.set_tracer_provider(provider)
                self._otel_tracer = trace.get_tracer(self.service_name)
                logger.info("OpenTelemetry OTLP Tracer initialized for service: %s -> %s", self.service_name, endpoint)
            except Exception as exc:
                logger.warning("OpenTelemetry OTLP setup failed (%s); using structured metric logging.", exc)


    @contextmanager
    def trace_span(self, operation: str, attributes: Optional[Dict[str, Any]] = None):
        """Context manager to measure latency and track execution status."""
        attrs = attributes.copy() if attributes else {}
        start_time = time.perf_counter()
        span_data = {
            "operation": operation,
            "start_time": time.time(),
            "attributes": attrs,
            "status": "ok",
        }
        otel_span = None
        if self._otel_tracer:
            try:
                otel_span = self._otel_tracer.start_span(operation)
                for k, v in attrs.items():
                    otel_span.set_attribute(str(k), str(v))
            except Exception:
                otel_span = None

        try:
            yield span_data
        except Exception as exc:
            span_data["status"] = "error"
            span_data["error"] = str(exc)
            if otel_span:
                otel_span.record_exception(exc)
            logger.error("Span error in operation '%s': %s", operation, exc)
            raise
        finally:
            if otel_span:
                otel_span.end()
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            span_data["duration_ms"] = elapsed_ms
            logger.info(
                "TRACE span='%s' duration=%.2fms status='%s' attrs=%s",
                operation,
                elapsed_ms,
                span_data["status"],
                span_data["attributes"],
            )
            self._metrics.append(span_data)
            # Keep bounded memory
            if len(self._metrics) > 1000:
                self._metrics.pop(0)

    def record_retrieval(
        self,
        query: str,
        roles: List[str],
        result_count: int,
        duration_ms: float,
        mode: str = "hybrid_rrf",
    ) -> None:
        """Record vector and full-text retrieval statistics."""
        data = {
            "event": "retrieval",
            "query_preview": query[:60],
            "roles": roles,
            "result_count": result_count,
            "duration_ms": duration_ms,
            "mode": mode,
            "timestamp": time.time(),
        }
        self._metrics.append(data)
        logger.info("RETRIEVAL mode=%s count=%d latency=%.2fms roles=%s", mode, result_count, duration_ms, roles)

    def record_generation(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
    ) -> None:
        """Record LLM token consumption and latency."""
        data = {
            "event": "generation",
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        }
        self._metrics.append(data)
        logger.info(
            "GENERATION model=%s tokens=%d latency=%.2fms",
            model,
            prompt_tokens + completion_tokens,
            duration_ms,
        )

    def record_chat_interaction(
        self,
        question: str,
        answer: str,
        roles: List[str],
        duration_ms: float,
        model: str = "gpt-4o",
    ) -> None:
        """Capture user question and AI response in Jaeger spans, tags, and events."""
        data = {
            "event": "chat_interaction",
            "question": question,
            "answer_preview": answer[:120],
            "roles": roles,
            "model": model,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        }
        self._metrics.append(data)
        logger.info("CHAT INTERACTION q=%r roles=%s latency=%.2fms", question[:50], roles, duration_ms)

        if self._otel_tracer:
            try:
                with self._otel_tracer.start_span("rag_chat_completion") as span:
                    span.set_attribute("rag.question", question)
                    span.set_attribute("rag.response", answer)
                    span.set_attribute("rag.roles", ",".join(roles))
                    span.set_attribute("rag.model", model)
                    span.set_attribute("rag.duration_ms", duration_ms)
                    span.add_event("user_question", {"content": question})
                    span.add_event("ai_response", {"content": answer})
            except Exception as exc:
                logger.debug("Failed exporting chat interaction to OTel: %s", exc)

    def get_recent_metrics(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._metrics[-limit:]

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Return aggregated summary counts of recorded telemetry and OTel status."""
        retrievals = [m for m in self._metrics if m.get("event") == "retrieval"]
        generations = [m for m in self._metrics if m.get("event") == "generation"]
        interactions = [m for m in self._metrics if m.get("event") == "chat_interaction"]
        error_spans = [m for m in self._metrics if m.get("status") == "error"]
        return {
            "service_name": self.service_name,
            "otel_active": self._otel_tracer is not None,
            "total_recorded_events": len(self._metrics),
            "retrieval_events": len(retrievals),
            "generation_events": len(generations),
            "chat_interactions": len(interactions),
            "error_spans": len(error_spans),
        }



tracer = ObservabilityTracer()

