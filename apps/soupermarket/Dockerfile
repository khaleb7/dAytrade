# syntax=docker/dockerfile:1
# Build from the repository root (the directory that contains apps/).
FROM gcr.io/distroless/python3-debian12
COPY apps/soupermarket/soupermarket /app/soupermarket

ENV PYTHONPATH=/app \
    SOUPER_BIND=0.0.0.0 \
    SOUPER_PORT=8080

WORKDIR /app
USER nonroot
EXPOSE 8080
ENTRYPOINT ["/usr/bin/python3", "-m", "soupermarket"]
