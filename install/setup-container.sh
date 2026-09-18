#!/usr/bin/env bash
# =============================================================================
# LeadScraper — Setup IM Container (idempotent, nur stdlib, keine pip-Deps)
# Wird vom Host-Installer via pct exec aufgerufen. Auch manuell re-runnable
# für Updates:  bash /opt/leadscraper/install/setup-container.sh
# Debugging: DEBUG=1 bash -x /opt/leadscraper/install/setup-container.sh
# =============================================================================
set -euo pipefail

APP="leadscraper"
APPDIR="/opt/leadscraper"
DATADIR="/var/lib/leadscraper"
WEB_PORT="${WEB_PORT:-${PORT:-8080}}"

fail() {
  local code=$?
  echo "==================================================================" >&2
  echo "[FATAL] Container-Setup fehlgeschlagen (Exit-Code: ${code})" >&2
  echo "Befehl : ${BASH_COMMAND}" >&2
  echo "Zeile  : ${BASH_LINENO[0]:-?}" >&2
  echo "--- Funktions-Stack ---" >&2
  local i
  for ((i=0; i<${#FUNCNAME[@]}; i++)); do
    echo "  #${i} ${FUNCNAME[$i]:-main} @ ${BASH_SOURCE[$i]}:${BASH_LINENO[$i]:-?}" >&2
  done
  echo "--- Relevante Logs ---" >&2
  systemctl status "${APP}.service" --no-pager 2>&1 | tail -n 30 >&2 || true
  journalctl -u "${APP}.service" --no-pager -n 50 2>&1 | tail -n 50 >&2 || true
  echo "Tipp: DEBUG=1 bash -x $0" >&2
  echo "==================================================================" >&2
  exit "${code}"
}
trap fail ERR
[[ "${DEBUG:-0}" == "1" ]] && set -x

echo "[1/7] Pakete (python3, sqlite3, curl) ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 sqlite3 curl

echo "[2/7] Verzeichnisse ..."
mkdir -p "${APPDIR}/app" "${DATADIR}"
test -f "${APPDIR}/app/app.py" || { echo "FEHLER: ${APPDIR}/app/app.py fehlt (Tarball-Push prüfen)." >&2; exit 1; }
test -f "${APPDIR}/icp/consulting-dach.json" || { echo "FEHLER: ICP-Profil fehlt." >&2; exit 1; }
python3 -m py_compile "${APPDIR}/app/app.py" || { echo "FEHLER: app.py kompiliert nicht." >&2; exit 1; }
python3 -c "import json; json.load(open('${APPDIR}/icp/consulting-dach.json'))" \
  || { echo "FEHLER: ICP-JSON ungültig." >&2; exit 1; }

echo "[3/7] systemd-Unit installieren ..."
cp "${APPDIR}/systemd/${APP}.service" "/etc/systemd/system/${APP}.service"
# Port aus Installer übernehmen (WEB_PORT), falls abweichend von 8080:
if [[ "${WEB_PORT}" != "8080" ]]; then
  sed -i "s/^Environment=PORT=.*/Environment=PORT=${WEB_PORT}/" "/etc/systemd/system/${APP}.service"
fi
systemctl daemon-reload
systemctl enable "${APP}.service"

echo "[4/7] Service (re)starten ..."
systemctl restart "${APP}.service"
sleep 4

echo "[5/7] Verifikation: Service aktiv?"
systemctl is-active --quiet "${APP}.service" || {
  echo "Service läuft NICHT. Voller Log:" >&2
  journalctl -u "${APP}.service" --no-pager -n 100 >&2
  exit 1
}
echo "  - Service: active"

echo "[6/7] Verifikation: HTTP-Check auf localhost:${WEB_PORT} ..."
for i in $(seq 1 15); do
  if curl -fsS "http://localhost:${WEB_PORT}/healthz"; echo; then
    echo "  - Web UI antwortet."
    break
  fi
  if [[ "$i" == "15" ]]; then
    echo "HTTP-Check fehlgeschlagen (15 Versuche)." >&2
    journalctl -u "${APP}.service" --no-pager -n 100 >&2
    ss -tlnp 2>/dev/null | grep "${WEB_PORT}" >&2 || true
    exit 1
  fi
  sleep 2
done

echo "[7/7] Fertig. URL: http://<LXC-IP>:${WEB_PORT} (Bind 0.0.0.0, onboot: 1 hostseitig)"
