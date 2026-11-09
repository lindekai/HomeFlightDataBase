FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server rsync python3 procps \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 flightdb \
 && useradd -m -u 1001 -g flightdb flightdb-sync \
 && usermod -p '*' flightdb-sync \
 && mkdir -p /run/sshd
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
HEALTHCHECK --interval=2s --retries=30 CMD test -f /keys/ingest_read && pgrep sshd
CMD ["/entrypoint.sh"]
