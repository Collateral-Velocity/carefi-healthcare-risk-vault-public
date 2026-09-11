# CareFi Healthcare Risk Vault

Prototype institutional capacity layer for healthcare event markets.

## CARE-HRV-01
**CARE-HRV-01 · Healthcare Event Risk Vault 2027** demonstrates how diversified capital could warehouse objectively settled healthcare event risk originated by CareFi and referenced by Oriel.

### V0.8
- Preloaded Texas respiratory-utilization contract from the Oriel Healthcare Event Risk Workbench.
- Common Oriel-to-CareFi JSON contract schema.
- Capacity decision with eligible notional, minimum price and capital consumed.
- Portfolio-impact view showing available capacity, weighted probability, expected P&L and indicative yield after allocation.
- Separation of Oriel reference analytics from CareFi underwriting/capital allocation.
- Defined vault mandate, eligible/ineligible contract universe, liquidity policy, valuation hierarchy, loss/distribution waterfall, governance, breach policy, token role and wind-down framework.
- Prototype economic term sheet in `CARE-HRV-01_TERM_SHEET.md`.
- Interactive HRV-E / HRV-M / HRV-S loss-waterfall and investor-return simulator.
- Event-driven stress engine tied directly to the six modeled healthcare positions; mild/moderate/severe scenarios are defined by actual trigger combinations, with non-trigger contract gains offsetting triggered-event losses.
- Custom trigger-combination builder plus a secondary arbitrary capital-stress override.
- MEDUSDi hedge toggle on capacity requests with gross, hedged and net healthcare-beta exposure.
- Portfolio-level MEDUSDi healthcare-beta dashboard using explicit illustrative factor assumptions.
- MEDUSDi-adjusted waterfall comparison showing tranche losses and investor returns with and without the hedge.
- Real NAV engine with modeled current Oriel marks, position-level unrealized P&L, settlement dates and status.
- Exact 64-state expected-loss analytics with 95%/99% loss quantiles and tranche impairment/wipeout probabilities.
- Cash/collateral dashboard covering posted event collateral, funded MEDUSDi hedge, liquidity reserve, free cash, cash yield and collateral-release ladder.
- Correlated Gaussian-copula joint-loss model preserving each event's marginal probability while modeling clustered respiratory, healthcare-inflation, reimbursement and specialty-drug triggers.
- Independent-vs-correlated comparison, joint-trigger probabilities, expected shortfall, and correlated HRV-E / HRV-M / HRV-S impairment and wipeout analytics.

### Architecture
- **Oriel** — public-print normalization, reference probability and valuation.
- **CareFi** — healthcare-risk origination, underwriting, capital allocation and portfolio construction.
- **Execution venue** — listing, execution and settlement.
- **CARE-HRV-01** — diversified institutional event-risk capacity.
- **Blockchain** — programmable ownership, allocation, NAV, waterfall and settlement-state accounting.

Research prototype only. Not an offering, executable quote or legal structure.
