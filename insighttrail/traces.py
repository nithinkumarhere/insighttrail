from flask import g

def trace_request(request, trace_id):
    # Generate a trace ID
    g.trace_id = trace_id
    print(f"Trace ID: {trace_id} for {request.method} {request.path}")
