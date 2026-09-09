#!/bin/sh
# Ripristina un backup estraendo SOLO i file archiviati.
#
# Il DB conversazioni e' escluso dal backup (R3A), quindi non e' nell'archivio e
# non viene reintrodotto: un conversations.sqlite3 gia' presente sul volume
# sopravvive al restore. Nessun transcript rientra da un archivio.
#
# Uso: restore.sh FILE [DEST]   (DEST default: directory corrente)
set -eu

file="${1:?manca FILE, es. restore.sh backups/treasureiq-....tgz [DEST]}"
dest="${2:-.}"

test -f "$file" || { echo "file non trovato: $file" >&2; exit 1; }

echo "questo sovrascrive i file curati/runtime in $dest con il contenuto di $file:" >&2
tar -tzf "$file" >&2
tar -xzf "$file" -C "$dest"
