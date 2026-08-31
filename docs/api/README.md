# API Design

Read-only API specification for slope-collector.

## Endpoints

### GET /sources

Returns all sources.

#### Response

```json
{
  "sources": [
    {
      "id": 1,
      "name": "..."
    }
  ]
}
```

### GET /entities

Returns entities. `source_id` is optional.

#### Query parameters

- `source_id`: Filter by source ID.

#### Examples

```text
GET /entities
GET /entities?source_id=1
```

#### Response

```json
{
  "entities": [
    {
      "id": 1,
      "source_id": 1,
      "name": "...",
      "is_active": true
    }
  ]
}
```

### GET /entities/{id}

Returns a single entity.

#### Response

```json
{
  "id": 1,
  "source_id": 1,
  "name": "...",
  "is_active": true
}
```

Returns `404 Not Found` when the entity does not exist.

### GET /records

Returns records with optional filters and pagination.

#### Query parameters

- `entity_id`: Filter by entity ID.
- `from`: Filter records published on or after this date.
- `to`: Filter records published on or before this date.
- `limit`: Number of records to return. Default: `20`. Maximum: `100`.
- `offset`: Number of records to skip. Default: `0`.

#### Examples

```text
GET /records
GET /records?entity_id=1
GET /records?entity_id=1&from=2026-01-01&to=2026-01-31
GET /records?limit=20&offset=20
```

#### Response

`body` and `assets` are omitted from list responses.

```json
{
  "records": [
    {
      "id": 1,
      "entity_id": 1,
      "title": "...",
      "source_url": "...",
      "published_at": "2026-01-15T12:00:00"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 123
  }
}
```

### GET /records/{id}

Returns a single record including its body and assets.

#### Response

```json
{
  "id": 123,
  "entity_id": 1,
  "title": "...",
  "body": "...",
  "source_url": "...",
  "published_at": "2026-01-15T12:00:00",
  "assets": [
    {
      "id": 10,
      "source_url": "...",
      "position": 0
    }
  ]
}
```

Returns `404 Not Found` when the record does not exist.

## Common Response Rules

- Responses use JSON.
- Date and time values use ISO 8601 format.
- API date/time values are handled consistently as UTC.
- Internal fields such as `created_at` and `updated_at` are not exposed unless required later.

## Error Response

Each error response has one top-level `code`. Detailed validation problems may be returned in the `errors` array.

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Request validation failed.",
  "errors": [
    {
      "field": "limit",
      "message": "Must be less than or equal to 100."
    },
    {
      "field": "offset",
      "message": "Must be greater than or equal to 0."
    }
  ]
}
```

`field` may be omitted when an error is not associated with a specific request field.

### Error codes

| HTTP status | Code | Usage |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | Invalid request outside normal field validation. |
| 404 | `NOT_FOUND` | Requested resource does not exist. |
| 422 | `VALIDATION_ERROR` | One or more request parameters are invalid. |
| 429 | `RATE_LIMIT_EXCEEDED` | Request rate limit exceeded. |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected server error. |

For `429 Too Many Requests`, the API should also return a `Retry-After` header when possible.
