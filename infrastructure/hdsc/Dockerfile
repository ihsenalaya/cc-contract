FROM nvidia/cuda:12.8.1-devel-ubuntu22.04@sha256:a99a1860ba8e2916e5c3e73b72ec4c4301653a84586e05bfc9a2aa2d58027e97 AS build
COPY src/cuda/continuity_worker.cu src/cuda/hdsc_dynamic_worker.cu /src/
RUN nvcc -std=c++17 -O2 -lineinfo -Xcompiler=-Wall,-Wextra -gencode arch=compute_90,code=sm_90 -gencode arch=compute_90,code=compute_90 /src/continuity_worker.cu -o /cc-continuity-worker && nvcc -std=c++17 -O2 -lineinfo -Xcompiler=-Wall,-Wextra -gencode arch=compute_90,code=sm_90 -gencode arch=compute_90,code=compute_90 /src/hdsc_dynamic_worker.cu -o /cc-hdsc-dynamic-worker
FROM nvidia/cuda:12.8.1-base-ubuntu22.04@sha256:001469ea0f3dec85a1ca929aeea3b58ae369d4c11228b10aec1f642bb6ca7a6f AS runtime
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ARG CC_COMMIT
LABEL org.opencontainers.image.source="https://github.com/ihsenalaya/cc-contract" org.opencontainers.image.revision="$CC_COMMIT"
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility LD_LIBRARY_PATH=/usr/local/lib PATH=/usr/local/cuda/compute-sanitizer:$PATH
COPY --from=build /cc-continuity-worker /cc-hdsc-dynamic-worker /usr/local/bin/
COPY --from=build /usr/local/cuda/compute-sanitizer /usr/local/cuda/compute-sanitizer
COPY --from=runtime /usr/local/cuda/lib64/libcudart.so.12 /usr/local/lib/libcudart.so.12
COPY src/ /app/src/
USER 10001:10001
ENTRYPOINT ["python3", "-m", "cc_contract.hdsc_rq2"]
CMD ["--backend", "cpu-model", "--output", "/tmp/rq2-development"]
