# Cinema PostgreSQL

Только PostgreSQL 17. Redis и миграции остаются в API.

[Выгрузка базы в бэкап](#выгрузка-базы-в-бэкап) ·
[Загрузка дампа в базу](#загрузка-дампа-в-базу-восстановление)

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

## Выгрузка базы в бэкап

Нужны Python 3 и SSH-доступ к узлу PostgreSQL. Все команды запускайте из папки
проекта базы. Адрес и логин задаются при запуске, пароль вводится скрыто.
Если адрес и логин не заданы, скрипт запросит их. Файл `APP` не используется.

### Windows (PowerShell)

Из `app_sources/database`:

```powershell
.\backup-db.ps1 -SshHost АДРЕС_СЕРВЕРА -SshUser SSH_ПОЛЬЗОВАТЕЛЬ
```

Другой SSH-порт: `-SshPort 2222`. Если Docker требует sudo, добавьте `-UseSudo`; нужен доступ к `sudo docker`
без запроса пароля. Скрипт сам найдёт контейнер сервиса `cinema_db_cinema-postgres`
(другое имя: `-Service ИМЯ`). При первом подключении сверяйте SSH-отпечаток сервера.

### Linux

Нужен Python 3 с модулем `venv`. Из папки проекта базы:

```bash
python3 -m venv .venv-db-backup
.venv-db-backup/bin/python -m pip install 'paramiko>=3.5,<5'
.venv-db-backup/bin/python backup-db.py --host АДРЕС_СЕРВЕРА --user SSH_ПОЛЬЗОВАТЕЛЬ
```

Пароль скрипт запросит при запуске. Другой SSH-порт: `--port 2222`.
Для Docker через sudo добавьте `--sudo` (без запроса пароля), для другого сервиса —
`--service ИМЯ`.

Результат: `app_sources/database/backups/ДАТА_БЭКАПА/`. На сервере файлы не создаются.
Окружение Python и доверенные SSH-ключи хранятся здесь же; пароль не сохраняется.
Нужно минимум 10 ГиБ свободного места; во время бэкапа не запускайте миграции.
Бэкап завершён, когда появился `backup-complete.json`; `.partial` не используйте.
Проверьте его восстановлением в отдельную локальную PostgreSQL 17. Храните копию
вне сервера; `globals.sql` может содержать хеши паролей.

## Загрузка дампа в базу (восстановление)

Восстанавливайте завершённый `cinema.dump` в пустую базу, до запуска API.
Замените `ДАТА_БЭКАПА`; команды ниже используют пользователя и базу `cinema`.

### Локально на Windows (PowerShell)

Запустите локальный Compose по разделу «Разработка». Затем из `app_sources/database`:

```powershell
.\restore-db.ps1 -DumpPath .\backups\ДАТА_БЭКАПА\cinema.dump
```

Временная копия дампа удаляется из контейнера; исходный файл и volume сохраняются.
После проверки данных примените миграции API.
Старые дампы в корне Cinema доступны по пути `..\..\backups\ДАТА_БЭКАПА\cinema.dump`.

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
