---
doc_key: CV-RPT-ORION-RCA
version: 1
title: Orion Telematics Root-Cause Report — Incident of 14 September 2026
tenant: corvane
collection: incidents
doc_type: report
classification: internal
acl_groups: [cv-ops, cv-procurement]
ethical_wall: []
matter: null
effective_date: 2026-09-22
amends: null
retention: 5y
parties: [Corvane Freight Holdings, Orion Telematics Ltd.]
tags: [contradiction]
---
# Orion Telematics Root-Cause Report — Incident of 14 September 2026

Orion Telematics Ltd. ("Orion") delivers this root-cause report to Corvane Freight Holdings ("Corvane") under the Service Level Agreement, ten (10) business days or fewer after the Severity 1 incident of 14 September 2026.

## 1. Executive Summary

1.1 Orion's monitoring shows that the Platform was degraded and then unavailable from 02:05 UTC to 03:19 UTC on 14 September 2026, a total outage of 74 minutes.

1.2 The cause was an expired signing certificate on the Orion ingest gateway, which caused the gateway to reject all vehicle telemetry messages.

## 2. Timeline

2.1 At 02:05 UTC the certificate expired and the gateway began rejecting messages. Automated alerts fired at 02:11 UTC but were routed to a retired on-call rota.

2.2 Corvane's incident call at 02:16 UTC was the first human contact. A replacement certificate was issued at 03:02 UTC and deployed at 03:19 UTC, when message flow resumed.

## 3. Customer Impact

3.1 Orion's logs show that 9 depots had live tracking interrupted. Depots served by the secondary regional gateway were not affected.

3.2 No telemetry data was lost. Messages queued on vehicle units were replayed after service resumed.

## 4. Service Credit Position

4.1 Orion has calculated the credit due under the Service Level Agreement on the basis of its 74-minute figure and will apply it to the November invoice, subject to Corvane's written claim.

4.2 Orion considers its own monitoring to be the authoritative source of outage duration for credit purposes.

## 5. Corrective Actions

5.1 Orion has moved certificate expiry alerts to a thirty (30) day warning schedule with named owners and has retired the old on-call rota.

5.2 A quarterly certificate inventory audit will be completed by 31 December 2026 and reported at the next service review.

5.3 Orion will offer a joint tabletop exercise with Corvane operations before 31 March 2027.

## 6. Lessons Learned

6.1 The incident showed that Orion's alert routing depended on a single rota that had not been reviewed after a team reorganisation. Orion will review all alert routes each quarter.

6.2 Orion apologises for the disruption to Corvane depots and will make its engineering lead available at the next service review to answer questions on this report.
