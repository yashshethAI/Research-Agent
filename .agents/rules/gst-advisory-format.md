# GST Practice Copilot Response Formatting Guidelines

## Section 2 Formatting Invariant
When synthesizing legal research opinions or memorandums:
1. **Heading**: Use `## 2. Legal and Statutory Explanation`.
2. **Bulleted Presentation**: Always present statutory analysis in clean, simplified bullet points (`- ...`). Do not produce monolithic narrative prose paragraphs.
3. **Thematic Organization**: Cover the legal position under 4 distinct, concise bullets:
   - **Governing Statutory Provision**: Core Section/Rule condition in plain English with clickable link.
   - **Date & Retrospective Applicability**: Historical vs current/retrospective provisions for the relevant period.
   - **CBIC Circular & Judicial Position**: Clarification from binding circulars or landmark court decisions.
   - **Direct Impact on Taxpayer**: Direct statutory conclusion and legal consequence for the client's case.
4. **Punchy & To the Point**: Maintain strictly 1–2 sentences per bullet. Strip out unnecessary legalese, repetitive commentary, and academic fluff.
5. **Inline Verified Links**: Every statutory section, rule, circular, or case citation must remain an active, clickable inline Markdown link pointing to verified official portals (e.g. `[Section 16(4) of the CGST Act](https://taxinformation.cbic.gov.in/...)`).

## Statutory Subject Alignment & Fiscal Calendar Rules
1. **Zero Hardcoded Provisions**: Align statutory citations strictly to their legal category (Charging/Levy ≠ Valuation ≠ ITC ≠ Returns ≠ Refunds ≠ Demands).
2. **Constitutional Roles**: The GST Council recommends (Article 279A); binding rate notifications are issued by Central/State Governments.
3. **Indian Financial Calendar (April 1 to March 31)**: Dates falling in preceding financial years must be framed as post-implementation audits (verifying invoices and Section 14 transitional time-of-supply rules), not future deadlines.
4. **ERP vs Portal Jurisdiction**: Rate tables, SKU-to-HSN mapping, and e-invoicing IRP templates belong to internal ERP systems (SAP/Tally), while `gst.gov.in` is reserved for return disclosures (GSTR-1, GSTR-3B, GSTR-9).
