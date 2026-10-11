-- Phase 4 step 2: exact vector search instead of the HNSW index.
--
-- Retrieval filters first (this patient's records or policies, never sensitive), which
-- leaves ~100-300 rows; comparing them all takes well under a millisecond and is exact.
-- With the HNSW index, Postgres could pick it and then apply the filters to its ~40
-- nearest candidates, sometimes returning too few or no rows. Without the index there
-- is nothing to pick. If chunks grow to hundreds of thousands, re-add an HNSW index and
-- set hnsw.iterative_scan (see evals/compare_vector_search.py).

drop index public.chunks_embedding_idx;
