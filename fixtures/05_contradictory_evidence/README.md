This fixture deliberately contains THREE different class counts across three
artifacts (config=8, dataset_metadata=9, train.log parsed_labels=10). Expected
behavior: lower confidence than Fixture 1, multiple competing hypotheses, and
explicit acknowledgment of the contradiction itself as part of the evidence
-- not a single confident guess at which number is "right."
