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
docker stack deploy -c deploy/stack.yml cinema-db
```

Один экземпляр закреплён за узлом, обновление выполняется `stop-first`.
Swarm создаёт volume `cinema-db_cinema_postgres_data` на этом узле.
Имя стека сохраняйте при обновлениях; метку не переносите на узел без данных.
Порт публикуется только на узле PostgreSQL (`mode: host`), номер задаётся через
`HOST_PORT` (по умолчанию `4932`). Для NAT настройте проброс TCP:
`внешний порт → IP узла PostgreSQL:HOST_PORT`.
Адрес привязки в Swarm через `ports` не задаётся: публикация идёт на всех
интерфейсах узла; доступ регулируется firewall и правилами NAT.
API подключите к `cinema-db-network`, хост базы
в `DATABASE_URL` — `cinema-db_postgres`, порт — `5432`.

## Автодеплой

Workflow `.github/workflows/deploy.yml` проверяет конфигурацию и вызывает
Portainer при push в `main` или ручном запуске GitHub Actions.
В Portainer создайте Git-стек из репозитория базы, ветки `main`, файла
`deploy/stack.yml`; задайте env и включите webhook. Его URL добавьте в GitHub
Secrets как `PORTAINER_WEBHOOK_URL`. Ответ webhook подтверждает приём запроса,
завершение обновления проверяйте в Portainer. Дамп автоматически не восстанавливается.

## Дамп

Восстановите дамп в новую пустую базу до подключения API. На узле базы найдите
контейнер, скопируйте в него `cinema.dump` и выполните:

```bash
docker ps --filter label=com.docker.swarm.service.name=cinema-db_postgres
docker cp cinema.dump CONTAINER_ID:/tmp/cinema.dump
docker exec CONTAINER_ID pg_restore -U cinema -d cinema --no-owner --no-privileges --single-transaction /tmp/cinema.dump
```

Проверьте данные, затем примените миграции API. Старый production остаётся
нетронутым. Репликация пока не настроена. В Swarm имя контейнера меняется:
старые скрипты с `cinema-prod-postgres` требуют адаптации. Не удаляйте volumes
и не увеличивайте `replicas` для создания репликации.
