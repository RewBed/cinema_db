# Cinema PostgreSQL

Только PostgreSQL 17. Redis и миграции остаются в API.

## Разработка

Скопируйте `.env.example` в `.env`, задайте пароль. Сеть `api_default` должна
существовать; другое имя задаётся через `POSTGRES_NETWORK_NAME` и
`CINEMA_NETWORK_NAME` API.

```bash
docker compose up -d postgres
```

Контейнер `cinema-postgres`; адрес и внешний порт задаются через `BIND_IP` и
`HOST_PORT`, по умолчанию `127.0.0.1:5432`. Compose сам создаёт volume
`database_cinema_postgres_data` при стандартном имени проекта `database`.
Старый volume не удаляется и автоматически не подключается.

## Production / Swarm

Используйте `deploy/stack.yml` в Portainer Swarm и переменные из
`deploy/.env.example`. Для CLI предварительно задайте их в окружении:
`docker stack deploy` самостоятельно не читает `.env`.

На manager назначьте метку **одному** выбранному узлу и создайте общую сеть:

```bash
docker node update --label-add cinema.postgres=primary NODE_NAME
docker network create --driver overlay --attachable cinema-db-network
docker stack deploy -c deploy/stack.yml cinema_db
```

Один экземпляр закреплён за узлом, обновление выполняется `stop-first`.
Swarm создаёт volume `cinema_db_cinema_postgres_data` на этом узле.
Имя стека сохраняйте при обновлениях; метку не переносите на узел без данных.
Порт публикуется только на узле PostgreSQL (`mode: host`), номер задаётся через
`HOST_PORT` (по умолчанию `4932`). Для NAT настройте проброс TCP:
`внешний порт → IP узла PostgreSQL:HOST_PORT`.
Адрес привязки в Swarm через `ports` не задаётся: публикация идёт на всех
интерфейсах узла; доступ регулируется firewall и правилами NAT.
API подключите к `cinema-db-network`, хост базы
в `DATABASE_URL` — `cinema_db_cinema-postgres`, порт — `5432`.

## Автодеплой

Workflow `.github/workflows/deploy.yml` проверяет конфигурацию и вызывает
Portainer при push в `main` или ручном запуске GitHub Actions.
В Portainer создайте Git-стек из репозитория базы, ветки `main`, файла
`deploy/stack.yml`; задайте env и включите webhook. Его URL добавьте в GitHub
Secrets как `PORTAINER_WEBHOOK_URL`. Ответ webhook подтверждает приём запроса,
завершение обновления проверяйте в Portainer. Дамп автоматически не восстанавливается.

## Быстрое восстановление из бэкапа

Восстанавливайте завершённый `cinema.dump` в пустую базу, до запуска API.
Замените `ДАТА_БЭКАПА`; команды ниже используют пользователя и базу `cinema`.

### Локально на Windows (PowerShell)

Запустите локальный Compose по разделу «Разработка». Затем из корня проекта:

```powershell
.\app_sources\database\restore-db.ps1 -DumpPath .\backups\ДАТА_БЭКАПА\cinema.dump
```

Временная копия дампа удаляется из контейнера; исходный файл и volume сохраняются.
После проверки данных примените миграции API.

### Восстановление на сервере (Linux)

Для запущенного стека `cinema_db`. Из PowerShell скопируйте дамп и подключитесь
к узлу PostgreSQL (замените `USER` и `SERVER`):

```powershell
scp .\backups\ДАТА_БЭКАПА\cinema.dump USER@SERVER:cinema.dump
ssh USER@SERVER
```

На сервере (имя сервиса — `ИМЯ_СТЕКА_ИМЯ_СЕРВИСА`; для текущего развёртывания
это `cinema_db_cinema-postgres`). Используйте завершённый дамп, не `.partial`:

```bash
db_container=$(sudo docker ps -q --filter label=com.docker.swarm.service.name=cinema_db_cinema-postgres)
echo "PostgreSQL container: $db_container"
test -n "$db_container" && sudo docker exec -i "$db_container" pg_restore -U cinema -d cinema --no-owner --no-privileges --single-transaction < ~/cinema.dump
sudo docker exec "$db_container" psql -U cinema -d cinema -c "SELECT count(*) FROM movies; SELECT count(*) FROM users; ANALYZE;"
```

Дамп читается напрямую из файла на сервере, без копирования в контейнер.
При ошибке восстановления транзакция откатывается; после успешного завершения
проверьте данные и примените миграции API. `globals.sql` здесь не нужен.
Старый production остаётся
нетронутым. Репликация пока не настроена. В Swarm имя контейнера меняется:
старые скрипты с `cinema-prod-postgres` требуют адаптации. Не удаляйте volumes
и не увеличивайте `replicas` для создания репликации.
