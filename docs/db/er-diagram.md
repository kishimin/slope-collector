# ER Diagram

```mermaid
erDiagram
    SOURCES ||--o{ ENTITIES : has
    ENTITIES ||--o{ RECORDS : has
    RECORDS ||--o{ ASSETS : has

    SOURCES {
        BIGINT_UNSIGNED id PK "AUTO_INCREMENT"
        VARCHAR_255 name "NOT NULL"
        DATETIME created_at "NOT NULL"
        DATETIME updated_at "NOT NULL"
    }

    ENTITIES {
        BIGINT_UNSIGNED id PK "AUTO_INCREMENT"
        BIGINT_UNSIGNED source_id FK,UK "NOT NULL"
        VARCHAR_255 name UK "NOT NULL"
        DATETIME created_at "NOT NULL"
        DATETIME updated_at "NOT NULL"
    }

    RECORDS {
        BIGINT_UNSIGNED id PK "AUTO_INCREMENT"
        BIGINT_UNSIGNED entity_id FK,UK "NOT NULL"
        VARCHAR_255 external_key UK "NOT NULL"
        VARCHAR_500 title "NOT NULL"
        LONGTEXT body "NOT NULL"
        VARCHAR_2048 source_url "NOT NULL"
        DATETIME published_at "NOT NULL"
        DATETIME created_at "NOT NULL"
        DATETIME updated_at "NOT NULL"
    }

    ASSETS {
        BIGINT_UNSIGNED id PK "AUTO_INCREMENT"
        BIGINT_UNSIGNED record_id FK,UK "NOT NULL"
        VARCHAR_2048 source_url "NOT NULL"
        INT_UNSIGNED position UK "NOT NULL"
        DATETIME created_at "NOT NULL"
        DATETIME updated_at "NOT NULL"
    }
```

## Key

- `PK`: Primary Key
- `FK`: Foreign Key
- `UK`: Unique Key. Multiple columns marked `UK` in the same table form a composite unique key where specified below.

## Unique Keys

- `entities`: `UNIQUE(source_id, name)`
- `records`: `UNIQUE(entity_id, external_key)`
- `assets`: `UNIQUE(record_id, position)`

## Foreign Keys

- `entities.source_id` → `sources.id` (`ON DELETE RESTRICT`)
- `records.entity_id` → `entities.id` (`ON DELETE RESTRICT`)
- `assets.record_id` → `records.id` (`ON DELETE RESTRICT`)

## Notes

- All primary keys use `BIGINT UNSIGNED AUTO_INCREMENT`.
