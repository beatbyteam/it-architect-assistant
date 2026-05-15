# Canonical Solution Flow

Core MVP flow:

1. Пользователь создаёт `task` свободным текстом.
2. Если входа недостаточно, система открывает `clarification request`.
3. После уточнений задача переходит в `ready_for_generation`.
4. Generation выпускает отдельный `solution version`.
5. Verification запускается отдельно и выпускает отдельный `verification protocol`.
6. Все шаги фиксируют `knowledge_version_id`, audit и operation log.
