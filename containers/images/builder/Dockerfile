FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        qemu-system-x86 qemu-utils cloud-image-utils genisoimage \
        openssh-client python3 curl ca-certificates zstd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work