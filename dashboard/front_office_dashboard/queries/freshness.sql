-- The banner every page shows (R6.1): when the extract was made, and the newest warehouse
-- modification among its tables. extract_info is the extract's own table, not a mart.
select extracted_at, warehouse_modified_at, git_commit
from marts.extract_info
order by warehouse_modified_at desc nulls last
limit 1
