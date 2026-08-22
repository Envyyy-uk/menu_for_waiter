#!/bin/bash
# Установка с нуля на чистый Ubuntu 24.04. Один запуск — рабочий POS.
#
#   ssh root@IP
#   curl -fsSL https://raw.githubusercontent.com/Envyyy-uk/menu_for_waiter/main/deploy/setup.sh -o setup.sh
#   bash setup.sh pos.вашезаведение.com
#
# Скрипт можно запускать повторно: он ничего не ломает и не перезаписывает
# уже созданный .env — на нём держатся пароль базы и ключи push, и потерять
# их значит отписать все телефоны от уведомлений.
set -euo pipefail

DOMAIN="${1:-}"
ROOT=/srv/pos
REPO=https://github.com/Envyyy-uk/menu_for_waiter.git
COMPOSE="docker compose --env-file $ROOT/.env -f $ROOT/deploy/docker-compose.prod.yml"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
die() { printf '\n\033[31mОшибка: %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "запускать от root: ssh root@IP"
[ -n "$DOMAIN" ] || die "укажите домен: bash setup.sh pos.вашезаведение.com"

export DEBIAN_FRONTEND=noninteractive
say "Обновляю список пакетов"
apt-get update -qq
apt-get install -y -qq curl ca-certificates

# ---------------------------------------------------------------- домен ---
# Caddy возьмёт сертификат сам, но только если домен уже смотрит сюда. Без
# этой проверки ошибка всплыла бы через две минуты, в чужом логе и без
# объяснений — а причина всегда одна и та же: A-запись не прописана или ещё
# не разошлась. Лучше упереться в это на первой секунде.
say "Проверяю домен $DOMAIN"
HERE=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
THERE=$(getent ahostsv4 "$DOMAIN" | awk '{print $1; exit}' || true)
if [ -z "$THERE" ]; then
	die "у $DOMAIN нет A-записи. Пропишите её на $HERE и подождите пару минут"
elif [ -n "$HERE" ] && [ "$HERE" != "$THERE" ]; then
	die "$DOMAIN ведёт на $THERE, а сервер — $HERE. Поправьте A-запись"
fi
echo "домен ведёт сюда: $THERE"

# -------------------------------------------------------------- система ---
say "Ставлю систему (это самая долгая часть, пара минут)"
apt-get upgrade -y -qq
apt-get install -y -qq docker.io docker-compose-v2 git ufw unattended-upgrades openssl
systemctl enable --now docker >/dev/null

# Обновления безопасности ставятся сами: без этого сервер стареет опасно.
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

# Наружу открыто только нужное. Базы среди этого нет — до неё дотягивается
# только сервер, изнутри docker-сети.
say "Закрываю всё лишнее в фаерволе"
ufw allow OpenSSH >/dev/null
ufw allow 80 >/dev/null
ufw allow 443 >/dev/null
ufw --force enable >/dev/null

# ---------------------------------------------------------- приложение ---
say "Скачиваю приложение"
if [ -d "$ROOT/.git" ]; then
	git -C "$ROOT" pull --ff-only
else
	git clone --depth 1 "$REPO" "$ROOT"
fi

PIN=""
if [ -f "$ROOT/.env" ]; then
	echo ".env уже есть — оставляю как был"
else
	say "Готовлю .env: пароли случайные, PIN владельца — тоже"
	# Шесть цифр: столько ждёт вход в админку. Первая не ноль — иначе PIN
	# читается как пятизначный и его набирают неправильно.
	PIN="$(( RANDOM % 9 + 1 ))$(printf '%05d' $(( RANDOM % 100000 )))"
	SECRET=$(openssl rand -hex 32)
	DBPASS=$(openssl rand -hex 24)

	cp "$ROOT/.env.example" "$ROOT/.env"
	sed -i \
		-e "s|^POS_DOMAIN=.*|POS_DOMAIN=$DOMAIN|" \
		-e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DBPASS|" \
		-e "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" \
		-e "s|^SEED_ADMIN_PIN=.*|SEED_ADMIN_PIN=$PIN|" \
		-e "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$DOMAIN|" \
		"$ROOT/.env"
	chmod 600 "$ROOT/.env"
fi

say "Собираю образ"
$COMPOSE build --quiet api

# Push без ключей выключается сам и разрешения зря не просит. Но раз мы всё
# равно здесь, заведём их сразу: потом это значит переподписывать телефоны.
if ! grep -q '^VAPID_PUBLIC_KEY=.\+' "$ROOT/.env"; then
	say "Завожу ключи для уведомлений"
	KEYS=$($COMPOSE run --rm --no-deps api python -m app.tools.vapid | grep '^VAPID_')
	PUB=$(echo "$KEYS" | grep '^VAPID_PUBLIC_KEY=' | cut -d= -f2)
	PRIV=$(echo "$KEYS" | grep '^VAPID_PRIVATE_KEY=' | cut -d= -f2)
	sed -i \
		-e "s|^VAPID_PUBLIC_KEY=.*|VAPID_PUBLIC_KEY=$PUB|" \
		-e "s|^VAPID_PRIVATE_KEY=.*|VAPID_PRIVATE_KEY=$PRIV|" \
		"$ROOT/.env"
fi

say "Запускаю"
$COMPOSE up -d --build

# ------------------------------------------------------------- бэкапы ---
# Снимок машины у хостера — раз в сутки, для кассы этого мало: между
# снимками теряется целый вечер. База выгружается отдельно, каждый час.
if ! crontab -l 2>/dev/null | grep -q 'pos/deploy/backup.sh'; then
	say "Ставлю почасовой бэкап базы"
	chmod +x "$ROOT/deploy/backup.sh"
	( crontab -l 2>/dev/null; echo "0 * * * * $ROOT/deploy/backup.sh >> /var/log/pos-backup.log 2>&1" ) | crontab -
fi

# --------------------------------------------------------------- итог ---
say "Жду, пока сервер ответит по HTTPS"
# Первый сертификат Let's Encrypt выписывается до минуты. Молчаливое
# ожидание здесь хуже ошибки: непонятно, идёт что-то или уже сломалось.
OK=""
for i in $(seq 1 40); do
	if curl -fsS --max-time 5 "https://$DOMAIN/health" >/dev/null 2>&1; then OK=1; break; fi
	printf '.'
	sleep 5
done
echo

if [ -n "$OK" ]; then
	printf '\n\033[32mГотово: https://%s\033[0m\n' "$DOMAIN"
else
	printf '\n\033[33mСервер поднят, но HTTPS ещё не ответил.\033[0m\n'
	echo "Смотрите лог:  $COMPOSE logs -f caddy"
fi

if [ -n "$PIN" ]; then
	printf '\nPIN владельца: \033[1m%s\033[0m — смените его при первом входе.\n' "$PIN"
	echo "Он же лежит в $ROOT/.env (SEED_ADMIN_PIN)."
fi
cat <<TXT

Дальше:
  1. Откройте https://$DOMAIN/admin/ и войдите этим PIN.
  2. Заведите персонал, расставьте столы, заполните склад.
  3. На телефонах и планшетах — «на домашний экран».

Полезное:
  логи        $COMPOSE logs -f api
  обновить    git -C $ROOT pull && $COMPOSE up -d --build
  бэкапы      $ROOT/backups
TXT
