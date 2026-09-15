# CARE-HRV-01 smart-contract prototype

This directory implements the first two on-chain components of the CareFi vault architecture.

## 1. Permissioned vault-share contracts

`VaultShareToken.sol` is an ERC-20-compatible accounting token used separately for HRV-S, HRV-M and HRV-E. Each class has independent supply and balances. Minting and burning are operator-controlled; ordinary transfers are allowed only when the shared eligibility registry approves both wallets and the sender is outside its lock-up.

The token deliberately does **not** implement AMM hooks, permissionless secondary trading, governance voting, lending, bridging, or automatic NAV pricing.

## 2. Eligibility / investor registry

`EligibilityRegistry.sol` stores the minimum on-chain state required to enforce transfer restrictions:

- active / inactive eligibility;
- permitted class bitmask (HRV-S, HRV-M, HRV-E);
- lock-up expiry;
- jurisdiction / compliance metadata hash;
- recovery-wallet metadata;
- approved compliance administrators;
- wallet replacement mapping.

No personally identifiable KYC data belongs on-chain. The registry stores only eligibility state and opaque hashes; KYC/AML files and the official legal investor register remain with the regulated administrator/provider.

## Wallet recovery

A compliance administrator calls `replaceWallet(old,new)`. That disables the old wallet and records the approved replacement. The share-token operator then calls `recoverWallet(old)` separately on each affected HRV class to migrate its complete balance to the approved replacement wallet.

## Deployment helper

`CAREHRV01ShareSuite.sol` deploys one registry plus:

- HRV-S — CARE-HRV-01 Senior Interest
- HRV-M — CARE-HRV-01 Mezzanine Interest
- HRV-E — CARE-HRV-01 Equity Interest

For a production deployment, ownership/operator roles should be transferred to the approved administrator or multisig rather than a personal EOA.

## Important boundary

These contracts are **prototype code and are not audited**. They do not themselves create or define the legal security, fund interest, CPO/SPV interest, subscription right, redemption right, or transfer-agent record. Legal rights must remain in the governing documents and official investor register. The smart contracts are intended to mirror and enforce approved economic-interest state.
