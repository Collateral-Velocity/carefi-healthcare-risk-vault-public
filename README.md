# CareFi Healthcare Risk Vault

Prototype institutional capacity layer for healthcare event markets.

## CARE-HRV-01
**CARE-HRV-01 · Healthcare Event Risk Vault 2027** demonstrates how diversified capital could warehouse objectively settled healthcare event risk originated by CareFi and referenced by Oriel.

### V0.4
- Preloaded Texas respiratory-utilization contract from the Oriel Healthcare Event Risk Workbench.
- Common Oriel-to-CareFi JSON contract schema.
- Capacity decision with eligible notional, minimum price and capital consumed.
- Portfolio-impact view showing available capacity, weighted probability, expected P&L and indicative yield after allocation.
- Separation of Oriel reference analytics from CareFi underwriting/capital allocation.
- Defined vault mandate, eligible/ineligible contract universe, liquidity policy, valuation hierarchy, loss/distribution waterfall, governance, breach policy, token role and wind-down framework.
- Prototype economic term sheet in `CARE-HRV-01_TERM_SHEET.md`.
- Interactive HRV-E / HRV-M / HRV-S loss-waterfall and investor-return simulator with mild, moderate, severe and custom portfolio-loss scenarios.

### Architecture
- **Oriel** — public-print normalization, reference probability and valuation.
- **CareFi** — healthcare-risk origination, underwriting, capital allocation and portfolio construction.
- **Execution venue** — listing, execution and settlement.
- **CARE-HRV-01** — diversified institutional event-risk capacity.
- **Blockchain** — programmable ownership, allocation, NAV, waterfall and settlement-state accounting.

Research prototype only. Not an offering, executable quote or legal structure.
