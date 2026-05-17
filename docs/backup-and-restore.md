# Local Backup And Restore

Локальные резервные копии защищают опубликованные решения, протоколы верификации, записи баз знаний, конфигурации развертки, и загруженные исходные документы от аппаратных сбоев и ошибок оператора.


Резервные копии являются артефактами только для оператора.
Они содержат дамп базы данных, загруженные документы и локальную конфигурацию развертывания, включая `.env.local`.

## Create Backup

Запустите локальный стек, затем выполните на Linux/macOS:

```bash
sh deploy/scripts/local_backup.sh --env-file .env.local --output-dir backups
```

На Windows PowerShell:

```powershell
.\deploy\scripts\local_backup.ps1 -EnvFile ".env.local" -OutputDir "backups"
```

Скрипт создает `backups/backup-YYYYMMDD-HHMMSS` с:

- `postgres.dump`: дамп PostgreSQL в custom-формате;
- `deployment_config.tgz` на Linux/macOS или `deployment_config.zip` на Windows: compose-файлы, deploy-скрипты, примеры файлов окружения и выбранный локальный env-файл;
- `knowledge_uploads.tgz`: загруженные документы базы знаний из volume с данными приложения;
- `manifest.json` и `SHA256SUMS`.

Архивные версии не удаляются при создании резервной копии или восстановлении. Архивные действия в приложении остаются мягким удалением; физическая очистка выполняется как отдельное административное действие.

## Restore Backup

Сначала проверьте `deployment_config.tgz` или `deployment_config.zip`, если локальную конфигурацию развертывания тоже нужно восстановить.

Восстановить базу данных и загруженные документы на Linux/macOS:
```bash
sh deploy/scripts/local_restore.sh --env-file .env.local --backup-dir backups/<backup-id>
```

На Windows PowerShell:

```powershell
.\deploy\scripts\local_restore.ps1 -EnvFile ".env.local" -BackupDir "backups\<backup-id>"
```

Скрипт восстановления останавливает сервисы приложения, пересоздаёт настроенную базу данных PostgreSQL, восстанавливает загруженные документы базы знаний и снова запускает стек. Если не передан параметр `--yes` или `-Yes` для PowerShell, скрипт запрашивает подтверждение.

## Operational Notes

- По возможности храните резервные копии вне репозитория.
- Не публикуйте архивы резервных копий: они могут содержать задачи, решения, протоколы, исходные документы и секреты из локальной конфигурации.
- Для восстановления на другой машине скопируйте директорию резервной копии, восстановите `.env.local` или пересоздайте его из `deployment_config.tgz`/`deployment_config.zip`, запустите Docker и выполните команду восстановления.
