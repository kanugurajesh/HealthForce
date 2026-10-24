# Evaluation results — provider `mock`

Synthetic dataset: 12 documents, 14 status-rule cases. As-of date 2026-10-23.

**credential detection**: precision = 1.0, recall = 1.0, spurious = 0, missed = 0, duplicates = 0

**credential fields**: field accuracy when stated = 0.944, stated values missed = 2, stated values wrong = 0, missing field detection = 1.0, values inferred when absent = 0, incorrectly inferred rate = 0.0

**experience**: recall = 0.889, precision = 0.889, date accuracy = 1.0

**qualifications**: precision = 0.833, recall = 1.0

**skills**: precision = 1.0, recall = 1.0

**evidence**: claims = 53, evidence located rate = 1.0, unsupported claims discarded = 0

**injection screen**: true positive = 1, false positive = 0, false negative = 0, true negative = 11

**credential status rules**: correct = 14, total = 14, accuracy = 1.0

## Individual errors

- 03_resume_unusual_dates.txt: RN_LICENSE.expiration_date missing (gold 2027-06-30)
- 03_resume_unusual_dates.txt: ACLS.expiration_date missing (gold 2027-08-31)
- 03_resume_unusual_dates.txt: missed experience 'RN, Emergency Department'
- 03_resume_unusual_dates.txt: spurious experience 'RN, Emergency Department, Bayside General Hospital'
- 12_resume_no_credentials.txt: spurious qual BSN
