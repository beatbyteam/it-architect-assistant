# ODA Core Principles

Этот документ входит в **обязательный пакет знаний MVP**.

Ключевые правила:
- одновременно существует только одна `active knowledge version`;
- generation и verification всегда фиксируют `knowledge_version_id` на старте и не перепривязываются по ходу выполнения;
- solution и verification protocol — это отдельные артефакты с разными жизненными циклами;
- проверка обязана ссылаться на документы-основания из active knowledge version;
- при неуспешном обновлении знаний предыдущая активная версия продолжает обслуживать generation и verification.
