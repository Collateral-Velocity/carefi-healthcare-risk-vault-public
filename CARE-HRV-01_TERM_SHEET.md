# CARE-HRV-01 — Prototype Economic Term Sheet

> **Status:** Research prototype for institutional discussion only. This document is not an offering memorandum, legal advice, investment advice, or a commitment to transact. Final terms would require counsel, administrator, venue, CPO/CTA and investor review.

## 1. Vehicle and mandate
**Vehicle:** CARE-HRV-01 · Healthcare Event Risk Vault 2027  
**Sponsor / risk administrator:** CareFi Capital, Inc. (prototype role)  
**Reference / valuation layer:** Oriel  
**Legal wrapper:** Single-purpose commodity pool, SPV or equivalent regulated institutional wrapper; exact form to be determined with counsel and participating CPO/administrator.  
**Mandate:** Provide diversified institutional capacity to objectively settled U.S. healthcare event markets.

The vault is intended to warehouse a diversified portfolio of healthcare event-contract exposures rather than replace the regulated venue, clearing, custody, CPO or SPV infrastructure supporting those positions.

## 2. Target capitalization and term
- **Target committed capital:** $10 million
- **Investment period:** Calendar 2027
- **Base term:** Through final settlement of all approved 2027-originated positions, plus an orderly wind-down period
- **Reinvestment:** Permitted during the investment period for realized proceeds, subject to concentration and liquidity tests
- **New subscriptions:** At designated dealing dates while the investment period is open and subject to capacity
- **Redemptions:** No ordinary redemption of capital supporting unresolved event positions; withdrawals occur only from unencumbered cash or at designated liquidity windows

## 3. Eligible contract universe
Eligible positions must:
1. Reference a healthcare utilization, medical-cost, reimbursement, healthcare-inflation, pharmacy/specialty-drug, or closely related healthcare-economic exposure.
2. Settle to an objective, independently published public print or rule-based observable.
3. Have unambiguous contract language, observation window, publication source, revision policy and fallback methodology.
4. Be executable on an approved venue or through an approved regulated structure.
5. Be capable of being independently valued by Oriel or another approved administrator/reference process.
6. Pass CareFi underwriting for basis risk, event probability, expected economics, duration and concentration.

**Illustrative approved sources:** CDC, BLS, CMS, BEA and other pre-approved governmental or independently administered public data sources.

**Ineligible without specific approval:** discretionary claims determinations, non-public client data as the sole settlement source, contracts with unresolved legal enforceability, contracts lacking a defined fallback, or exposures whose settlement is materially controlled by the protection buyer or seller.

## 4. Concentration and underwriting limits
- **Single-event capital-at-risk limit:** 12.5% of NAV
- **Risk-family capital-at-risk limit:** 30% of NAV
- **Single-geography capital-at-risk limit:** 25% of NAV
- **Counterparty / venue limit:** Set by risk committee before live deployment
- **Public-print/source concentration:** Monitored and subject to override if operational dependence becomes excessive
- **Minimum basis-risk grade:** Normally B+; lower grades require explicit exception
- **Exceptions:** Require documented risk-committee approval and must be disclosed in vault reporting

Capacity is determined on capital at risk, not headline notional alone.

## 5. Capital and collateral policy
- Vault capital supporting an executed event position is treated as encumbered until settlement or approved close-out.
- Collateral is held through the applicable venue, clearing arrangement, custodian or approved account structure.
- Unencumbered cash may be held in cash, U.S. Treasury bills, government money-market instruments or other short-duration instruments permitted by final fund documents.
- No leverage is assumed in the base prototype.
- Any future financing, surety, reinsurance or collateral-advance arrangement must be separately approved and transparently reflected in NAV and risk reporting.

## 6. Valuation and NAV policy
**NAV frequency:** Monthly, with event-driven updates after material public prints or settlements.  
**Primary mark hierarchy:**
1. Executable two-sided venue market, where sufficiently liquid and representative.
2. Oriel fair-value estimate using public-print history, market inputs and documented model assumptions.
3. Independent administrator or risk-committee fair value when neither of the above is reliable.

Unrealized positions are marked to fair value rather than held at entry price. Oriel model changes must be version-controlled. Material methodology changes require disclosure. Resolved contracts are valued at contractual settlement value once the outcome is objectively determined, subject to venue finality.

## 7. Liquidity policy
The vault is not designed as daily-liquidity capital. Investor liquidity is subordinate to the duration of the underlying event positions.

- No redemption may force liquidation of an unresolved position solely to satisfy an investor withdrawal.
- Unencumbered cash can be distributed at designated liquidity windows.
- A reserve may be maintained for fees, operating expenses and settlement uncertainty.
- Final return of capital follows settlement or transfer/close-out of all positions attributable to the relevant capital.

## 8. Economic waterfall
The prototype contemplates three tokenized economic-interest classes while the legal ownership remains in the regulated wrapper:

- **HRV-S — Senior:** first priority in distributions; last to absorb portfolio losses
- **HRV-M — Mezzanine:** receives distributions after Senior; absorbs losses after Equity and before Senior
- **HRV-E — Equity / first-loss:** residual economics; first to absorb portfolio losses

**Loss order:** HRV-E → HRV-M → HRV-S  
**Distribution order:** operating expenses and reserves → HRV-S entitlement → HRV-M entitlement → residual to HRV-E

Exact attachment points, coupons/preferred returns and class sizes are intentionally left configurable pending investor demand and legal/tax review. The app should not imply that the current tranche labels are securities already offered or issued.

## 9. Fees and expenses
Prototype assumptions:
- **Management / administration fee:** TBD
- **Performance / incentive allocation:** TBD
- **Venue, clearing, custody, legal, audit, tax, data and administrator costs:** borne as defined in final documents
- No fee is included in the current indicative-yield calculation unless explicitly shown.

## 10. Governance and approvals
CareFi acts as prototype risk administrator. A live vehicle should have a documented risk committee or equivalent approval process.

The approval record for each position should include:
- contract specification and settlement source
- Oriel reference probability / valuation
- basis-risk grade
- requested and approved capacity
- concentration impact
- expected return / loss economics
- venue / counterparty
- legal and operational exceptions
- approving persons and timestamp

## 11. Breach, exception and remediation
A passive limit breach caused by NAV movement or correlated losses does not automatically force liquidation. The risk administrator may:
1. stop new allocations to the affected bucket,
2. reduce or hedge exposure when practical,
3. allow the exposure to run off,
4. seek risk-committee approval for a temporary exception.

Any active breach created by a new trade must be approved in advance.

## 12. Settlement-source and venue disruption
Every position must specify a fallback before execution.

If a public-print source is delayed, revised, discontinued or materially changed, the contractual fallback controls. If the fallback itself fails, the position follows the venue's rulebook or governing transaction documents. Oriel may provide a reference determination but does not unilaterally rewrite executed contract terms.

If a venue, clearer or custodian is impaired, capital recovery and valuation follow the governing legal documents. The vault reports the affected position separately as operational/counterparty exposure.

## 13. Token role
The token is a programmable record of economic interest and accounting state, not a substitute for the legal wrapper.

It may record:
- beneficial/economic interest
- subscription and transfer history
- class / tranche
- NAV entitlement
- deployed and unencumbered capital
- realized loss allocation
- distributions
- settlement status

Transfers, whitelisting, investor eligibility and secondary trading remain subject to applicable law and final fund documents.

## 14. Reporting
Illustrative investor reporting includes:
- NAV and NAV per class
- deployed vs. available capital
- open positions and public-print sources
- capital at risk by event, family and geography
- realized and unrealized P&L
- Oriel reference value and methodology version
- limit utilization and exceptions
- settlement calendar
- fees and expenses

## 15. Wind-down
After the investment period, no new risk is added except defensive transactions or approved close-outs. As positions settle, proceeds move to unencumbered cash and are distributed under the waterfall after reserves and expenses. The vehicle terminates after all positions and liabilities are resolved.

---

### Prototype design principle
**Oriel standardizes and values the risk. CareFi originates, underwrites and allocates capital. The venue executes and settles. The regulated wrapper owns the positions. The token records the economic interest and state of the vault.**
