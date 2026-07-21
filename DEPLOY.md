# Деплой на VPS

Я сделал деплой максимально простым: Docker собирает API, рядом поднимается Postgres, worker, Caddy для HTTPS и контейнер с бэкапами.

## 1. Что поставить на VPS

На чистом сервере нужны только git и Docker с compose plugin.

```bash
apt update
apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sh
```

Потом клонирую проект, например так:

```bash
mkdir -p /opt
cd /opt
git clone <repo-url> mangalclubs-core
cd mangalclubs-core
```

## 2. Настроить env

```bash
cp .env.deploy.example .env
nano .env
```

Главное поменять:

- `POSTGRES_PASSWORD` - пароль от базы.
- `JWT_SECRET_KEY` - длинная случайная строка.
- `DOMAIN` - домен API. Если домена пока нет, можно временно поставить `DOMAIN=:80`.
- `CORS_ORIGINS` - адреса фронта.
- `PUBLIC_API_BASE_URL` - публичный адрес API, например `https://api.example.ru`.
- `TBANK_DEFAULT_TERMINAL_KEY` и `TBANK_DEFAULT_PASSWORD` - пока тестовые от T-Bank. Потом просто меняю эти же строки на боевые.

Для генерации секрета можно так:

```bash
openssl rand -hex 32
```

## 3. Запуск

```bash
docker compose up -d --build
```

Миграции Alembic запускаются сами перед стартом API.

Проверка:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

Если `DOMAIN` нормальный и DNS уже смотрит на VPS, Caddy сам выпустит HTTPS-сертификат.

## 4. Обновление

Вручную:

```bash
sh scripts/deploy.sh
```

Чтобы обновлялось само, можно добавить cron:

```bash
crontab -e
```

И вставить:

```cron
*/10 * * * * cd /opt/mangalclubs-core && sh scripts/deploy.sh >> /var/log/mangalclubs-deploy.log 2>&1
```

Так сервер раз в 10 минут проверяет репозиторий, пересобирает контейнеры и перезапускает их.

## 5. Бэкапы

Бэкапы складываются в папку:

```bash
./backups
```

Там будут:

- `mangalclubs_YYYYMMDD-HHMMSS.dump` - база Postgres.
- `media_YYYYMMDD-HHMMSS.tar.gz` - загруженные файлы.

По умолчанию хранятся 14 дней. Меняется через `BACKUP_KEEP_DAYS` в `.env`.

Восстановить базу можно так:

```bash
docker compose exec -T postgres pg_restore -U mangalclubs -d mangalclubs --clean --if-exists < backups/mangalclubs_YYYYMMDD-HHMMSS.dump
```

Media восстановить так:

```bash
tar -xzf backups/media_YYYYMMDD-HHMMSS.tar.gz -C media
```

## 6. Полезные команды

Логи API:

```bash
docker compose logs -f api
```

Логи worker:

```bash
docker compose logs -f worker
```

Остановить:

```bash
docker compose down
```

Adminer я не держу включенным постоянно, чтобы не есть память. Если надо посмотреть базу:

```bash
docker compose --profile tools up -d adminer
```

Потом открыть через SSH tunnel на `127.0.0.1:8080`.
