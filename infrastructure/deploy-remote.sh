#!/bin/bash
# 服务器端部署步骤，由 infrastructure/deploy.ps1 上传后在后台运行，输出写到 /tmp/healthos-deploy.out。
# 前提：/tmp/healthos-src.tgz（git archive）和 /tmp/healthos-web.tgz（frontend/out）已上传。
set -uo pipefail

APP_DIR=/root/workspace/HealthOS
BACKUP_DIR=/root/backups
TS=$(date +%Y%m%d%H%M)

fail() { echo "FAILED: $*"; exit 1; }

cd "$APP_DIR" || fail "no $APP_DIR"
mkdir -p "$BACKUP_DIR"

echo "== backup $TS"
docker compose exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' </dev/null \
  > "$BACKUP_DIR/healthos-before-deploy-$TS.dump" || fail "pg_dump"
tar -czf "$BACKUP_DIR/web-before-deploy-$TS.tar.gz" web || fail "web backup"
ls -la "$BACKUP_DIR/healthos-before-deploy-$TS.dump"

echo "== extract source"
tar -xzf /tmp/healthos-src.tgz -C "$APP_DIR" || fail "extract source"
# 测试阶段：对外开放 8080（仓库里默认只监听 127.0.0.1）
sed -i 's/"127.0.0.1:8080:80"/"8080:80"/' docker-compose.yml

echo "== build api"
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ docker compose build api </dev/null 2>&1 | tail -3
[ "${PIPESTATUS[0]}" -eq 0 ] || fail "build"

echo "== up (migrate runs first)"
docker compose up -d api caddy </dev/null 2>&1 | tail -5
docker compose logs --tail 3 migrate </dev/null
# Caddyfile 是单文件挂载，解压后是新文件，需要重启 caddy 才能读到
docker compose restart caddy </dev/null 2>&1 | tail -1

echo "== web (keep old hashed assets for cached pages)"
find web -mindepth 1 -maxdepth 1 ! -name _next -exec rm -rf {} +
[ -d web/_next ] && find web/_next -mindepth 1 -maxdepth 1 ! -name static -exec rm -rf {} +
tar -xzf /tmp/healthos-web.tgz -C web || fail "extract web"
# 旧的带哈希资源保留 30 天
find web/_next/static -type f -mtime +30 -delete

echo "== backup cron"
install -m 700 infrastructure/backup.sh /usr/local/bin/healthos-backup
mkdir -p "$BACKUP_DIR/daily"
echo "30 3 * * * root /usr/local/bin/healthos-backup >> $BACKUP_DIR/daily/backup.log 2>&1" > /etc/cron.d/healthos-backup
chmod 644 /etc/cron.d/healthos-backup
# 部署前的备份保留最近 10 份
ls -1t "$BACKUP_DIR"/healthos-before-*.dump 2>/dev/null | tail -n +11 | xargs -r rm -f
ls -1t "$BACKUP_DIR"/web-before-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "== check"
sleep 3
docker compose ps </dev/null
health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/health)
page=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/)
echo "health=$health page=$page"
[ "$health" = 200 ] && [ "$page" = 200 ] || fail "health check"
rm -f /tmp/healthos-src.tgz /tmp/healthos-web.tgz
echo "DONE rollback: $BACKUP_DIR/healthos-before-deploy-$TS.dump $BACKUP_DIR/web-before-deploy-$TS.tar.gz"
