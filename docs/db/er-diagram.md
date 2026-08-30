# ER Diagram

```mermaid
erDiagram
    SOURCES ||--o{ ENTITIES : has
    ENTITIES ||--o{ RECORDS : has
    RECORDS ||--o{ ASSETS : has

    SOURCES {
        BIGINT id PK "UNSIGNED, AUTO_INCREMENT"
        VARCHAR name "VARCHAR(255), NOT NULL"
        DATETIME created_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP"
        DATETIME updated_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP"
    }

    ENTITIES {
        BIGINT id PK "UNSIGNED, AUTO_INCREMENT"
        BIGINT source_id FK,UK "UNSIGNED, NOT NULL"
        VARCHAR name UK "VARCHAR(255), NOT NULL"
        BOOLEAN is_active "NOT NULL, DEFAULT TRUE"
        DATETIME created_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP"
        DATETIME updated_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP"
    }

    RECORDS {
        BIGINT id PK "UNSIGNED, AUTO_INCREMENT"
        BIGINT entity_id FK,UK "UNSIGNED, NOT NULL"
        VARCHAR external_key UK "VARCHAR(255), NOT NULL"
        VARCHAR title "VARCHAR(500), NOT NULL"
        LONGTEXT body "NOT NULL"
        VARCHAR source_url "VARCHAR(2048), NOT NULL"
        DATETIME published_at "NOT NULL"
        DATETIME created_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP"
        DATETIME updated_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP"
    }

    ASSETS {
        BIGINT id PK "UNSIGNED, AUTO_INCREMENT"
        BIGINT record_id FK,UK "UNSIGNED, NOT NULL"
        VARCHAR source_url "VARCHAR(2048), NOT NULL"
        INT position UK "UNSIGNED, NOT NULL"
        DATETIME created_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP"
        DATETIME updated_at "NOT NULL, DEFAULT CURRENT_TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP"
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
- `entities.is_active` is a boolean flag and defaults to `TRUE`.
- `created_at` defaults to `CURRENT_TIMESTAMP`.
- `updated_at` defaults to `CURRENT_TIMESTAMP` and is automatically updated with `ON UPDATE CURRENT_TIMESTAMP`.
- `records.published_at` is source data and has no default value.
