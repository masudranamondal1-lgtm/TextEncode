# TextEncode Data Model

## New Foundation Tables (Phase 1)

### `projects`
*   `project_id` (PK)
*   `name`
*   `description`
*   `created_at`

### `corpora`
*   `corpus_id` (PK)
*   `project_id` (FK)
*   `name`
*   `description`

### `evidence_bundles` (Phase 2)
*   `evidence_id` (PK)
*   `relationship_id` (FK)
*   `evidence_domain` ('literary', 'historical', 'geographical')
*   `source_text`
*   `context`
*   `confidence`
*   `notes`

## Object Distinctions
*   **Entity:** The concept (e.g., "Ichhamati River").
*   **Mention:** The specific text span.
*   **Evidence:** The proof.
