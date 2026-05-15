# Architecture Principles

Система должна поддерживать только одну active knowledge version одновременно.

Generation и verification должны ссылаться на active knowledge version и сохранять source refs.

При неуспешном knowledge refresh предыдущая active knowledge version должна остаться без изменений.
