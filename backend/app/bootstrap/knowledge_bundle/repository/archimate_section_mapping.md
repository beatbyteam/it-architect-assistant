# ArchiMate 3.2 Section Mapping

Документ строится по TOGAF, но содержимое архитектурных разделов описывается через объекты метамодели ArchiMate 3.2.

## Бизнес-архитектура
Допустимы: Business Actor, Business Role, Business Process, Business Function, Business Service, Business Event, Business Object.

## Архитектура данных
Допустимы: Data Object, Business Object, Representation, а также прикладные сущности, которые создают, читают или публикуют данные.

## Архитектура приложений
Допустимы: Application Component, Application Interface, Application Service, Application Function, Application Process, Application Event.

## Технологическая архитектура
Допустимы: Node, Device, System Software, Network, Technology Service, Technology Function, Artifact.

Принцип проверки: объект считается корректным только если его можно отнести к разрешённому списку сущностей для текущего раздела.
