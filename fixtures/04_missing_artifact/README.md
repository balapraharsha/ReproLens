This fixture deliberately omits dataset_metadata.json to test the
missing_information path -- the upload UI should still allow investigation
with fewer than 5 artifacts, and the diagnosis should surface the gap
rather than silently ignoring it or crashing.
