FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ARG CC_COMMIT
LABEL org.opencontainers.image.title="CC-Contract CPU model" \
      org.opencontainers.image.source="https://github.com/ihsenalaya/cc-contract" \
      org.opencontainers.image.revision="$CC_COMMIT"
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CC_COMMIT=$CC_COMMIT
WORKDIR /app
COPY --chown=10001:10001 src/ /app/src/
USER 10001:10001
ENTRYPOINT ["python3", "-m", "cc_contract.cli"]
CMD ["selftest", "--emit-records"]
