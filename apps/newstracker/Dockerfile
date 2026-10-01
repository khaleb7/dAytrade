# syntax=docker/dockerfile:1
# Build from the repository root (the directory that contains apps/).
FROM gcr.io/distroless/python3-debian12

COPY apps/newstracker/newstracker /app/newstracker

ENV PYTHONPATH=/app \
    NEWSTRACKER_DB=/data/newstracker.db \
    NEWSTRACKER_BIND=0.0.0.0 \
    NEWSTRACKER_PORT=8080

WORKDIR /app
USER nonroot
EXPOSE 8080
ENTRYPOINT ["/usr/bin/python3", "-m", "newstracker"]
