# Schema Overview

## batches
| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| id | integer | NO | nextval('batches_id_seq'::regclass) |
| assay_id | integer | YES |  |
| display_name | character varying | YES |  |
| date_created | timestamp without time zone | YES |  |
| date_prepared | timestamp without time zone | YES |  |
| last_updated | timestamp without time zone | YES |  |
| sample_ids | ARRAY | NO |  |
| test_ids | ARRAY | NO |  |
| raw_payload | jsonb | NO |  |
| fetched_at | timestamp with time zone | NO | now() |

## customers
| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| id | integer | NO | nextval('customers_id_seq'::regclass) |
| name | character varying | NO |  |
| date_created | timestamp without time zone | YES |  |
| raw_payload | jsonb | NO |  |
| fetched_at | timestamp with time zone | NO | now() |

## orders
| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| id | integer | NO | nextval('orders_id_seq'::regclass) |
| custom_formatted_id | character varying | YES |  |
| customer_account_id | integer | NO |  |
| date_created | timestamp without time zone | YES |  |
| date_completed | timestamp without time zone | YES |  |
| date_order_reported | timestamp without time zone | YES |  |
| date_received | timestamp without time zone | YES |  |
| sample_count | integer | YES |  |
| test_count | integer | YES |  |
| state | character varying | YES |  |
| raw_payload | jsonb | NO |  |
| fetched_at | timestamp with time zone | NO | now() |

## samples
| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| id | integer | NO | nextval('samples_id_seq'::regclass) |
| sample_name | character varying | YES |  |
| custom_formatted_id | character varying | YES |  |
| order_id | integer | NO |  |
| has_report | boolean | NO |  |
| batch_ids | ARRAY | NO |  |
| completed_date | timestamp without time zone | YES |  |
| date_created | timestamp without time zone | YES |  |
| start_date | timestamp without time zone | YES |  |
| matrix_type | character varying | YES |  |
| state | character varying | YES |  |
| test_count | integer | YES |  |
| sample_weight | numeric | YES |  |
| raw_payload | jsonb | NO |  |
| fetched_at | timestamp with time zone | NO | now() |

## tests
| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| id | integer | NO | nextval('tests_id_seq'::regclass) |
| sample_id | integer | NO |  |
| batch_ids | ARRAY | NO |  |
| date_created | timestamp without time zone | YES |  |
| state | character varying | YES |  |
| has_report | boolean | NO |  |
| report_completed_date | timestamp without time zone | YES |  |
| label_abbr | character varying | YES |  |
| title | character varying | YES |  |
| worksheet_raw | jsonb | YES |  |
| raw_payload | jsonb | NO |  |
| fetched_at | timestamp with time zone | NO | now() |
