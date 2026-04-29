#!/bin/sh
# Sincronizza la porta BT di qBittorrent con la porta forwardata da Proton/Gluetun.
# Gira nel network namespace di gluetun (qBit raggiungibile come localhost:8080).

set -u

PORT_FILE=/gluetun/forwarded_port
QBIT=http://localhost:8080
INTERVAL="${INTERVAL:-60}"
COOKIE=/tmp/qbit.cookie

LOG() { printf '[%s] %s\n' "$(date -u '+%F %T UTC')" "$*"; }

login() {
    rm -f "$COOKIE"
    if curl -sf --max-time 10 -c "$COOKIE" \
        -d "username=$QBIT_USER&password=$QBIT_PASS" \
        "$QBIT/api/v2/auth/login" >/dev/null; then
        # qBit response is "Ok." or "Fails."
        # SID cookie is what we actually need
        if grep -q SID "$COOKIE" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

set_port() {
    local port=$1
    curl -sf --max-time 10 -b "$COOKIE" \
        --data-urlencode "json={\"listen_port\":$port,\"upnp\":false,\"random_port\":false}" \
        "$QBIT/api/v2/app/setPreferences" >/dev/null
}

LAST_PORT=""
LOG "qb-port-manager started — polling every ${INTERVAL}s, qBit user=$QBIT_USER"

while true; do
    if [ -s "$PORT_FILE" ]; then
        PORT=$(tr -d '[:space:]' < "$PORT_FILE")
        if [ -n "$PORT" ] && [ "$PORT" != "$LAST_PORT" ]; then
            LOG "Forwarded port changed: ${LAST_PORT:-<none>} -> $PORT"
            if login; then
                if set_port "$PORT"; then
                    LOG "qBit listen_port updated to $PORT"
                    LAST_PORT=$PORT
                else
                    LOG "setPreferences API call failed"
                fi
            else
                LOG "Login to qBit failed (creds o qBit non pronto)"
            fi
        fi
    fi
    sleep "$INTERVAL"
done
