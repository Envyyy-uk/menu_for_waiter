#!/bin/sh
# Выгрузка базы раз в час.
#
# Снимок всей машины у хостера снимается раз в сутки — для кассы этого мало:
# между снимками теряется целый вечер. Здесь выгружается только база, она
# крошечная, и за две недели таких файлов набирается меньше сотни мегабайт.
#
#   0 * * * * /srv/pos/deploy/backup.sh >> /var/log/pos-backup.log 2>&1
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)

# Cron запускается с пустым окружением, а имя пользователя базы лежит в .env.
# Без этой строки бэкап молча уходил бы в базу `pos` даже там, где она другая.
if [ -f "$ROOT/.env" ]; then
	. "$ROOT/.env"
fi

OUT="$ROOT/backups"
KEEP_DAYS=14
STAMP=$(date +%Y-%m-%d-%H)

mkdir -p "$OUT"

docker compose --env-file "$ROOT/.env" -f "$ROOT/deploy/docker-compose.prod.yml" exec -T db \
	pg_dump -U "${POSTGRES_USER:-pos}" "${POSTGRES_DB:-pos}" \
	| gzip > "$OUT/pos-$STAMP.sql.gz.tmp"

# Готовый файл появляется одним движением: оборванная выгрузка не должна
# выглядеть как целый бэкап.
mv "$OUT/pos-$STAMP.sql.gz.tmp" "$OUT/pos-$STAMP.sql.gz"

find "$OUT" -name 'pos-*.sql.gz' -mtime +$KEEP_DAYS -delete
find "$OUT" -name '*.tmp' -mtime +1 -delete

echo "$(date '+%F %T') бэкап готов: $(du -h "$OUT/pos-$STAMP.sql.gz" | cut -f1)"
