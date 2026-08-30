# ER Diagram

```mermaid
erDiagram
    SOURCES ||--o{ ENTITIES : has
    ENTITIES ||--o{ RECORDS : has
    RECORDS ||--o{ ASSETS : has

    SOURCES {
        BIGINT id PK
        VARCHAR code UK
        VARCHAR name
        VARCHAR status
        DATETIME created_at
        DATETIME updated_at
    }

    ENTITIES {
        BIGINT id PK
        BIGINT source_id FK
        VARCHAR name
        VARCHAR status
        DATETIME created_at
        DATETIME updated_at
    }

    RECORDS {
        BIGINT id PK
        BIGINT entity_id FK
        VARCHAR external_key
        VARCHAR title
        LONGTEXT body
        VARCHAR source_url
        DATETIME published_at
        DATETIME created_at
        DATETIME updated_at
    }

    ASSETS {
        BIGINT id PK
        BIGINT record_id FK
        VARCHAR source_url
        INT position
        DATETIME created_at
        DATETIME updated_at
    }
```

## Constraints

- All primary keys use `BIGINT UNSIGNED AUTO_INCREMENT`.
- `sources.code` is unique.
- `entities` has a unique constraint on `(source_id, name)`.
- `records` has a unique constraint on `(entity_id, external_key)`.
- `assets` has a unique constraint on `(record_id, position)`.
- `sources.status` and `entities.status` are represented by application-side string enums.
