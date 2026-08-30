# ER Diagram

```mermaid
erDiagram
    SOURCES ||--o{ ENTITIES : has
    ENTITIES ||--o{ RECORDS : has
    RECORDS ||--o{ ASSETS : has

    SOURCES {
        BIGINT_UNSIGNED id PK "AUTO_INCREMENT"
        VARCHAR_64 code UK "NOT NULL"
        VARCHAR_255 name "NOT NULL"
        VARCHAR_32 status "NOT NULL"
        DATETIME created_at "NOT NULL"
        DATETIME updated_at "NOT NULL"
    }

    ENTITIES {
        BIGINT_UNSIGNED id PK "AUTO_INCREMENT"
        BIGINT_UNSIGNED source_id FK,UK "NOT NULL"
        VARCHAR_255 name UK "NOT NULL"
        VARCHAR_32 status "NOT NULL"
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

- `sources`: `UNIQUE(code)`
- `entities`: `UNIQUE(source_id, name)`
- `records`: `UNIQUE(entity_id, external_key)`
- `assets`: `UNIQUE(record_id, position)`

## Notes

- All primary keys use `BIGINT UNSIGNED AUTO_INCREMENT`.
- `sources.status` and `entities.status` are represented by application-side string enums.
