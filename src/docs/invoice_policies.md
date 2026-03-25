# Invoice Processing Policies

## 1. Invoice Acceptance Criteria

All invoices submitted for processing must meet the following minimum requirements:

- Must include a valid invoice number unique to the vendor.
- Must include a vendor name matching an approved vendor in the registry.
- Must include an invoice date (not future-dated by more than 7 days).
- Must include a clearly stated total amount in an accepted currency.
- Must reference a valid purchase order number where applicable.

Invoices failing to meet these criteria are flagged for manual review and held pending correction.

## 2. Payment Approval Thresholds

Invoice payment approvals follow a tiered authorization model based on invoice amount:

- **Up to $4,999.99**: Auto-approved if all validations pass and no anomalies are detected.
- **$5,000 to $24,999.99**: Requires Level 1 approval from a direct manager.
- **$25,000 to $99,999.99**: Requires Level 2 approval from the Financial Controller.
- **$100,000 and above**: Requires Level 3 approval from VP Finance or CFO.

Emergency payments above $100,000 require dual authorization (two L3 approvers).

## 3. Vendor Payment Terms

Standard payment terms are Net 30 from invoice date unless a vendor contract specifies otherwise.

- Legal and Audit vendors: Net 60.
- Staffing vendors: Net 14 (bi-weekly).
- Technology SaaS vendors: Net 30.

Early payment discounts should be captured in the PO notes field and applied automatically.

## 4. Duplicate Invoice Policy

An invoice is considered a duplicate if an invoice with the same invoice number AND vendor name has been processed within the preceding 90 calendar days. Duplicate invoices are:

1. Automatically blocked from payment.
2. Escalated to the AP Supervisor for investigation.
3. Logged in the audit trail with reference to the original invoice.

Vendors must resubmit with a corrected (unique) invoice number if the original was issued in error.

## 5. PO Variance Policy

Invoice amounts must be within 10% of the associated purchase order amount. Invoices exceeding this threshold require:

- Investigation by the AP team to confirm the variance is legitimate.
- Approval from the PO originator confirming scope change.
- Updated PO documentation if the variance represents a change order.

Variances greater than 35% are escalated to the Financial Controller regardless of invoice amount.

## 6. OCR and Document Quality

Invoices processed via OCR (scanned documents) are subject to a minimum confidence threshold of 85%. Invoices below this threshold are:

- Held in the verification queue.
- Assigned to an AP analyst for manual field verification.
- Reprocessed once the analyst confirms or corrects the extracted fields.

Vendors are encouraged to submit native digital PDFs to avoid OCR processing delays.

## 7. Currency Policy

Accepted currencies for invoice processing: USD, CAD, EUR, GBP, AUD, JPY, CHF.

All invoices in foreign currencies are converted to USD at the rate published by the corporate treasury on the invoice date. Exchange rate variances are tracked separately for FX reporting.

## 8. Stale Invoice Policy

Invoices dated more than 180 days in the past are considered stale. Stale invoices require:

- AP Supervisor approval before processing.
- Confirmation that the goods or services were received in the period indicated.
- GL posting to the correct accounting period (prior period adjustment if applicable).
