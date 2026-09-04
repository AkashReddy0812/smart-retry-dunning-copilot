import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

def setup_tracing(service_name: str):
    """
    Sets up OpenTelemetry tracing, configures the OTLP exporter, 
    and sets the global tracer provider.
    """
    # Create a Resource identifying the service
    resource = Resource(attributes={
        "service.name": service_name
    })

    # Create the TracerProvider with the service resource
    provider = TracerProvider(resource=resource)

    # Configure the OTLP Exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)

    # Wrap the exporter in a BatchSpanProcessor and attach it
    span_processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(span_processor)

    # Set as the global tracer provider
    trace.set_tracer_provider(provider)

    return provider

def get_tracer(name: str):
    """
    Returns a tracer instance for creating manual spans.
    """
    return trace.get_tracer(name)