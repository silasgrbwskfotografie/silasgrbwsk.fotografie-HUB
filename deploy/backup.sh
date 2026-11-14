#!/bin/bash
# Sicherung außerhalb des Servers (Studio-Tool, läuft auf dem VPS per cron, nicht im Container).
# Packt die frische Datenbank-Sicherung und den Upload-Ordner in ein Archiv, behält 14 Tages- und 6 Monatsstände
# und kopiert das Archiv per rclone an ein Ziel außerhalb des Servers (zum Beispiel ein verschlüsseltes pCloud-Remote).
#
# Einrichten (einmalig, Silas):  rclone config   (Remote anlegen, Zugangsdaten tippt Silas selbst)
# cron (crontab -e als tigershub):
#   30 3 * * * RCLONE_REMOTE=pcloud-crypt:studio-tool /opt/docker/apps/app2/deploy/backup.sh >> /opt/docker/apps/app2/offsite/backup.log 2>&1
set -euo pipefail

APP=${APP:-/opt/docker/apps/app2}
ZIEL="$APP/offsite"
REMOTE=${RCLONE_REMOTE:-}
mkdir -p "$ZIEL"

# Frische, konsistente Kopie der Datenbank (SQLite-Backup-API, auch während des Betriebs)
docker exec studio-tool python -c "import server; print(server.daily_backup(neu=True))"
db=$(ls -1 "$APP"/data/backups/studio-????-??-??.db | sort | tail -1)
stamp=$(date +%F)
tar -czf "$ZIEL/studio-$stamp.tar.gz.tmp" -C "$APP/data" "backups/$(basename "$db")" uploads
mv "$ZIEL/studio-$stamp.tar.gz.tmp" "$ZIEL/studio-$stamp.tar.gz"
echo "$(date '+%F %T') Archiv: studio-$stamp.tar.gz ($(du -h "$ZIEL/studio-$stamp.tar.gz" | cut -f1))"

# Aufräumen: die letzten 14 Archive, dazu das erste Archiv jedes der letzten 6 Monate
mapfile -t alle < <(ls -1 "$ZIEL"/studio-????-??-??.tar.gz | sort)
behalten=$(printf '%s\n' "${alle[@]: -14}"; printf '%s\n' "${alle[@]}" | awk '{m=substr($0, length($0)-16, 7); if (!(m in s)) {s[m]=1; print}}' | tail -6)
for f in "${alle[@]}"; do
  grep -qxF "$f" <<< "$behalten" || rm -f -- "$f"
done

if [ -n "$REMOTE" ]; then
  rclone copy "$ZIEL/studio-$stamp.tar.gz" "$REMOTE/"
  # copy statt sync: ein versehentlich leerer Ordner auf dem Server löscht so nie die Sicherungen am Ziel
  rclone delete "$REMOTE/" --min-age 190d --include "studio-*.tar.gz"
  echo "$(date '+%F %T') nach $REMOTE kopiert"
else
  echo "WARNUNG: RCLONE_REMOTE ist nicht gesetzt, die Sicherung liegt nur auf dem Server."
fi
