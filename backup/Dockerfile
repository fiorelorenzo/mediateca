FROM alpine:3.20

RUN apk add --no-cache restic sqlite openssh-client bash tini ca-certificates

COPY backup.sh /usr/local/bin/backup.sh
COPY restore-check.sh /usr/local/bin/restore-check.sh
COPY excludes.txt /etc/backup/excludes.txt
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore-check.sh

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/local/bin/backup.sh"]
