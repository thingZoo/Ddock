# Admin skill raw replay fixtures

`pass_1_classification_fenced_response.txt` is the exact `raw_output` string
preserved from the first local Admin-skill G0 acceptance run. It is test-only
evidence for the parser failure caused by a single Markdown JSON fence.

`pass_1_classification_truncated_response.txt` is the exact `raw_output` string
from the later compact PASS 1 run. It ends during the 185th utterance ID and is
test-only evidence that the balanced parser rejects incomplete JSON rather than
repairing or fabricating the missing tail.

The fixture must never be imported by production runtime code or used to branch
on its video ID, utterance IDs, timestamps, workflow titles, or content. Tests
may replay its serialization shape and verify that the final utterance is present.
