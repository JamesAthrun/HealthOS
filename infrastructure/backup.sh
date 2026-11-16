#!/bin/bash
# HealthOS 每日备份：数据库（pg_dump 自定义格式）+ 照片，保留最近 KEEP_DAYS 天。
# 安装（服务器上，root）：
#   install -m 700 infrastructure/backup.sh /usr/local/bin/healthos-backup
#   echo '30 3 * * * root /usr/local/bin/healthos-backup >> /root/backups/daily/backup.log 2>&1' > /etc/cron.d/healthos-backup
# 恢复数据库：docker compose exec -T postgres sh -c 'pg_restore -c -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < healthos-YYYYmmdd-HHMM.dump
# 恢复照片：tar -xzf photos-YYYYmmdd-HHMM.tar.gz -C "$(docker volume inspect -f '{{.Mountpoint}}' healthos_photos_data)"
set -euo pipefail

APP_DIR=${APP_DIR:-/root/workspace/HealthOS}
OUT_DIR=${OUT_DIR:-/root/backups/daily}
KEEP_DAYS=${KEEP_DAYS:-14}
PHOTO_VOLUME=${PHOTO_VOLUME:-healthos_photos_data}
TS=$(date +%Y%m%d-%H%M)

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
cd "$APP_DIR"

# 把结果写进数据库，管理员总览里能看到最近一次备份；写入失败不影响备份本身
record_run() {
  docker compose exec -T -e B_OK="$1" -e B_DB="$2" -e B_PH="$3" -e B_MSG="$4" postgres \
    sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v ok="$B_OK" -v db_bytes="$B_DB" -v photos_bytes="$B_PH" -v message="$B_MSG"' \
    >/dev/null 2>&1 <<'SQL' || echo "(未能写入 backup_runs)"
INSERT INTO backup_runs (id, finished_at, ok, db_bytes, photos_bytes, message)
VALUES (gen_random_uuid(), now(), :ok, NULLIF(:'db_bytes', '')::bigint, NULLIF(:'photos_bytes', '')::bigint, :'message');
SQL
}
trap 'record_run false "" "" "backup failed at line $LINENO"' ERR

db_file="$OUT_DIR/healthos-$TS.dump"
docker compose exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' </dev/null > "$db_file.tmp"
# 备份文件必须能被 pg_restore 读出目录，否则视为失败
docker compose exec -T postgres pg_restore --list < "$db_file.tmp" > /dev/null
mv "$db_file.tmp" "$db_file"

photo_dir=$(docker volume inspect -f '{{.Mountpoint}}' "$PHOTO_VOLUME")
tar -czf "$OUT_DIR/photos-$TS.tar.gz.tmp" --exclude='*.thumb.jpg' -C "$photo_dir" .
mv "$OUT_DIR/photos-$TS.tar.gz.tmp" "$OUT_DIR/photos-$TS.tar.gz"

chmod 600 "$OUT_DIR"/healthos-*.dump "$OUT_DIR"/photos-*.tar.gz
find "$OUT_DIR" -maxdepth 1 \( -name 'healthos-*.dump' -o -name 'photos-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete
find "$OUT_DIR" -maxdepth 1 -name '*.tmp' -mmin +60 -delete

trap - ERR
record_run true "$(stat -c %s "$db_file")" "$(stat -c %s "$OUT_DIR/photos-$TS.tar.gz")" "ok"
echo "$(date '+%F %T') ok db=$(du -h "$db_file" | cut -f1) photos=$(du -h "$OUT_DIR/photos-$TS.tar.gz" | cut -f1)"
