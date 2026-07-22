# Деплой на VPS

Эта инструкция для запуска backend и web на VPS. На сервере поднимаются:

- API приложения;
- Postgres;
- worker для фоновых задач;
- Next.js web;
- Caddy, чтобы принять HTTP/HTTPS снаружи и прокинуть запросы в API и web;
- контейнер с ежедневными бэкапами базы и media-файлов.

Обновление делаю вручную, когда сам решу выкатить новую версию.

## 1. Что подготовить

Нужен VPS на Ubuntu/Debian, доступ по SSH и репозиторий с кодом в GitHub/GitLab/Bitbucket.

`.env` в git не заливаю. На сервере он будет отдельным файлом.

Если есть домен, сразу делаю DNS:

- `A` запись `api.example.ru` на IP VPS;
- `A` запись `example.ru` на IP VPS.

Если домена пока нет, можно сначала запускать по IP через HTTP.

## 2. Зайти на VPS

```bash
ssh root@SERVER_IP
```

Обновляю пакеты и ставлю git + Docker:

```bash
apt update
apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sh
```

Если включен firewall, открываю SSH, HTTP и HTTPS:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

## 3. Залить код

Сначала код надо залить в git-репозиторий. Лучше приватный.

Потом на VPS:

```bash
mkdir -p /opt
cd /opt
git clone <core-repo-url> mangalclubs-core
git clone <web-repo-url> mangalclubs-web
cd mangalclubs-core
```

Если репозиторий приватный, на сервере нужен доступ: deploy key, SSH-ключ или HTTPS token.

## 4. Настроить `.env`

```bash
cp .env.deploy.example .env
nano .env
```

Что обязательно поменять:

- `POSTGRES_PASSWORD` - нормальный пароль от базы.
- `JWT_SECRET_KEY` - длинная случайная строка.
- `DOMAIN` - домен API, например `api.example.ru`.
- `WEB_DOMAIN` - основной домен сайта, например `example.ru`.
- `WEB_DIR` - путь до frontend относительно backend, если оба репозитория лежат в `/opt`, оставляю `../mangalclubs-web`.
- `PUBLIC_API_BASE_URL` - публичный адрес API, например `https://api.example.ru`.
- `NEXT_PUBLIC_API_URL` - публичный адрес API для сборки frontend.
- `NEXT_PUBLIC_SITE_URL` - публичный адрес сайта для сборки frontend.
- `TBANK_DEFAULT_TERMINAL_KEY` и `TBANK_DEFAULT_PASSWORD` - тестовые данные терминала T-Bank. Потом эти же строки меняются на боевые.

Секрет можно сгенерировать так:

```bash
openssl rand -hex 32
```

Если домена пока нет:

```env
DOMAIN=:80
PUBLIC_API_BASE_URL=http://SERVER_IP
COOKIE_SECURE=false
```

Когда появится домен и HTTPS, возвращаю:

```env
DOMAIN=api.example.ru
WEB_DOMAIN=example.ru
PUBLIC_API_BASE_URL=https://api.example.ru
NEXT_PUBLIC_API_URL=https://api.example.ru
NEXT_PUBLIC_SITE_URL=https://example.ru
COOKIE_SECURE=true
```

### CORS

`CORS_ORIGINS` нужен в основном для браузера: web-фронта, админки, локальной разработки.

Для обычного мобильного приложения CORS обычно не нужен, потому что это ограничение браузера. Поэтому туда указываю адреса web-фронта, например:

```env
CORS_ORIGINS=https://example.ru,https://www.example.ru
```

Если мобильное приложение открывает web-часть внутри WebView или есть Expo web, тогда добавляю туда именно web-адрес этой части.

`*` лучше не ставить, потому что в API включены cookies/credentials.

## 5. Первый запуск

```bash
docker compose up -d --build
```

Миграции Alembic запускаются автоматически перед стартом API.

Проверка:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

Если `DOMAIN` указан как домен и DNS уже смотрит на VPS, Caddy сам получит HTTPS-сертификат.

Снаружи проверяю так:

```bash
curl https://api.example.ru/health
curl -I https://example.ru
curl https://example.ru/health
```

Или без домена:

```bash
curl http://SERVER_IP/health
```

## 6. Обновление вручную

Когда надо выкатить новую версию:

```bash
cd /opt/mangalclubs-core
sh scripts/deploy.sh
```

Скрипт делает:

- `git pull --ff-only`;
- пересборку Docker image;
- перезапуск контейнеров;
- очистку старых Docker images.

Автообновление по cron не включаю. Так меньше сюрпризов на сервере.

## 7. Бэкапы

Бэкапы складываются на сервере в папку:

```bash
/opt/mangalclubs-core/backups
```

Там будут:

- `mangalclubs_YYYYMMDD-HHMMSS.dump` - база Postgres;
- `media_YYYYMMDD-HHMMSS.tar.gz` - загруженные файлы.

По умолчанию хранится 14 дней. Меняется в `.env`:

```env
BACKUP_KEEP_DAYS=14
```

Восстановить базу:

```bash
docker compose exec -T postgres pg_restore -U mangalclubs -d mangalclubs --clean --if-exists < backups/mangalclubs_YYYYMMDD-HHMMSS.dump
```

Восстановить media-файлы в Docker volume:

```bash
docker run --rm \
  -v mangalclubs-core_mangalclubs_media:/media \
  -v /opt/mangalclubs-core/backups:/backups \
  alpine sh -c "cd /media && tar -xzf /backups/media_YYYYMMDD-HHMMSS.tar.gz"
```

## 8. Полезные команды

Логи API:

```bash
docker compose logs -f api
```

Логи worker:

```bash
docker compose logs -f worker
```

Логи бэкапов:

```bash
docker compose logs -f backup
```

Перезапустить API:

```bash
docker compose restart api
```

Остановить все:

```bash
docker compose down
```

Посмотреть базу через Adminer:

```bash
docker compose --profile tools up -d adminer
```

Adminer слушает только `127.0.0.1`, поэтому открываю через SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 root@SERVER_IP
```

Потом в браузере:

```text
http://127.0.0.1:8080
```

Данные для входа:

- system: `PostgreSQL`
- server: `postgres`
- username: значение `POSTGRES_USER`
- password: значение `POSTGRES_PASSWORD`
- database: значение `POSTGRES_DB`
