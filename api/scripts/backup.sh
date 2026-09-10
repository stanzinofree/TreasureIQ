#!/bin/sh
# Backup dei dati curati/runtime, ESCLUSO il DB conversazioni (R3A).
#
# Il transcript (data-live/conversations.sqlite3 + sidecar) e' stato temporaneo
# soggetto alla retention applicativa (TTL 90gg + purge): non va replicato in
# archivi di lunga durata. Vedi docs/workstreams/storage-lifecycle/analysis.md.
#
# Uso: backup.sh [ROOT]   (ROOT default: directory corrente)
# Opera sui path relativi a ROOT (data/storico.db, data-live/). Stampa su stdout
# UNA sola riga: il path del .tgz creato (cosi' e' catturabile da make e test).
# I messaggi informativi vanno su stderr.
set -eu

root="${1:-.}"
cd "$root"

# Glob del DB conversazioni: DB + eventuali sidecar (-wal, -shm, -journal).
conversation_db_glob='data-live/conversations.sqlite3*'

mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
tar_path="backups/treasureiq-$stamp.tgz"

# --exclude prima dei path: richiesto da bsdtar (macOS), accettato da GNU tar.
if [ -f data/storico.db ]; then
	tar --exclude="$conversation_db_glob" -czf "$tar_path" data/storico.db data-live
else
	echo "data/storico.db assente, backup solo di data-live/" >&2
	tar --exclude="$conversation_db_glob" -czf "$tar_path" data-live
fi

echo "backup: $tar_path (DB conversazioni escluso, R3A)" >&2
echo "$tar_path"
