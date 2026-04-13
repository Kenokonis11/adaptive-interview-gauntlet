# YAML_SCHEMA.md
## Job Config Format — Schema and Annotated Example

---

### Purpose

Each YAML file represents one target role. It is the only input the system needs to personalize the entire session — study guide, question context, skill proxies, and test datasets all derive from it.

---

### Schema

```yaml
# Required fields
target_company: string
role: string
mastery_alpha: float  # optional, default 0.3 — how aggressively to update scores

core_requirements:
  - string  # plain language skill names; must match keys used in user_mastery.json

skill_proxies:
  - original_skill: string      # must match one entry in core_requirements
    proxy_type: string          # "python_pandas" | "sql_duckdb" | "python_general"
    proxy_context: string       # natural language description for Hiring Manager
    test_dataset: string        # inline CSV, path to file, or DuckDB CREATE TABLE statement
    difficulty_default: string  # "warm_up" | "standard" | "stretch"

non_executable_skills:          # optional — skills that get LLM-as-judge only
  - skill: string
    evaluation_rubric: string   # what a good written answer covers
```

---

### MVP Example — ACME Corp Data Scientist

```yaml
target_company: "ACME Corp"
role: "Data Scientist — Analytics Platform"
mastery_alpha: 0.3

core_requirements:
  - "pandas_merge_and_groupby"
  - "window_functions_sql"
  - "null_handling_pandas"
  - "data_visualization_proxy"  # Tableau proxy — tested via data prep logic

skill_proxies:

  - original_skill: "pandas_merge_and_groupby"
    proxy_type: "python_pandas"
    proxy_context: >
      ACME's analytics pipeline joins two datasets daily: a user activity log
      (user_id, event_date, event_type, duration_seconds) and a user profile table
      (user_id, region, account_tier). The candidate must write a Pandas function
      that merges these tables, groups by region and account_tier, and returns
      the total and average duration per group — handling users who appear in
      activity but not in the profile table.
    test_dataset: |
      activity:
        user_id: [1, 2, 3, 4]
        event_date: ["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-01"]
        event_type: ["click", "view", "click", "purchase"]
        duration_seconds: [30, 120, 45, null]
      profiles:
        user_id: [1, 2, 3]
        region: ["US", "EU", "US"]
        account_tier: ["premium", "free", "premium"]
    difficulty_default: "standard"

  - original_skill: "window_functions_sql"
    proxy_type: "sql_duckdb"
    proxy_context: >
      ACME tracks user listening sessions in a table: sessions(user_id INT, session_date DATE, minutes FLOAT).
      Some users log zero minutes on days they open the app but don't listen.
      The candidate must write a SQL query that calculates the 7-day rolling average
      of listening minutes per user, including days with zero minutes in the average
      (not skipping them), and excluding days with NULL minutes from the denominator.
    test_dataset: |
      CREATE TABLE sessions (user_id INT, session_date DATE, minutes FLOAT);
      INSERT INTO sessions VALUES
        (1, '2024-01-01', 30.0),
        (1, '2024-01-02', 0.0),
        (1, '2024-01-03', NULL),
        (1, '2024-01-04', 45.0),
        (2, '2024-01-01', 60.0),
        (2, '2024-01-02', 20.0);
    difficulty_default: "standard"

  - original_skill: "null_handling_pandas"
    proxy_type: "python_pandas"
    proxy_context: >
      ACME receives daily CSV exports from a third-party vendor. The files frequently
      contain nulls in numeric columns, mixed-type columns (numbers stored as strings),
      and occasional duplicate rows. The candidate must write a cleaning function that:
      (1) drops exact duplicate rows, (2) coerces numeric columns to float,
      (3) fills nulls in numeric columns with the column median, and
      (4) returns a clean DataFrame with a boolean 'was_modified' column added.
    test_dataset: |
      raw_data:
        id: [1, 2, 2, 3, 4]
        revenue: ["100.5", "200", "200", null, "abc"]
        clicks: [10, null, 20, 30, 5]
    difficulty_default: "warm_up"

  - original_skill: "data_visualization_proxy"
    proxy_type: "python_pandas"
    proxy_context: >
      ACME's BI team needs to build a regional performance dashboard in Tableau.
      The dashboard requires a clean, aggregated dataset: one row per region per week,
      with columns for total_revenue, avg_order_value, and week-over-week revenue growth rate.
      The candidate must write the Pandas logic that produces this exact output from
      a raw orders table (order_id, region, order_date, order_value).
      The viz layer is assumed — only the data prep is tested.
    test_dataset: |
      orders:
        order_id: [1, 2, 3, 4, 5, 6]
        region: ["US", "US", "EU", "EU", "US", "EU"]
        order_date: ["2024-01-01", "2024-01-03", "2024-01-02", "2024-01-08", "2024-01-08", "2024-01-09"]
        order_value: [100, 200, 150, 300, 250, 175]
    difficulty_default: "standard"

non_executable_skills: []
# No non-executable skills in MVP — everything has a code proxy
```

---

### Adding a Non-Executable Skill (Future Extension)

```yaml
non_executable_skills:
  - skill: "stakeholder_communication"
    evaluation_rubric: >
      A strong answer should cover: (1) tailoring technical complexity to audience,
      (2) leading with the business implication before the methodology,
      (3) anticipating and addressing objections, (4) using concrete metrics.
      Judge scores 0.0-1.0 on coverage of these four points.
```

For non-executable skills, the Hiring Manager asks the question verbally, the candidate responds in text, and the Judge evaluates the written response against the rubric. No MCP call is made.
