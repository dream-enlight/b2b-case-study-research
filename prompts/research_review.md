Process only review_cases, up to the supplied review_batch_size (default 20).
Cases may span providers: competing_products[provider] (or the supplied
competing_product) controls each case's scope.
Reuse assigned evidence and any saved_record. Exclude clear metadata irrelevance
without opening; otherwise read as deeply as necessary to decide, stopping when
irrelevance is established. Relevant substantive reading requires the complete
record during this reading. Emit case_result with assigned id, decision
(relevant|excluded|unresolved), reason, evidence, record and contribution. A relevant
record must have status="complete"; excluded/unresolved decisions have record=null.
Contribution describes observed customer need/workflow, never eligibility or advice.
