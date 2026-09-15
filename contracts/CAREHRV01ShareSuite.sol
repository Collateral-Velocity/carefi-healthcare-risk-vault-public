// SPDX-License-Identifier: BUSL-1.1
pragma solidity ^0.8.24;

import "./EligibilityRegistry.sol";
import "./VaultShareToken.sol";

/// @title CARE-HRV-01 Share Suite
/// @notice Deploys the eligibility registry and the three permissioned economic-interest classes.
/// @dev Prototype deployment helper. Production ownership should be transferred to the approved
///      administrator/multisig and reviewed by securities, commodities, tax and fund counsel.
contract CAREHRV01ShareSuite {
    EligibilityRegistry public immutable registry;
    VaultShareToken public immutable hrvSenior;
    VaultShareToken public immutable hrvMezzanine;
    VaultShareToken public immutable hrvEquity;

    constructor(address administrator) {
        registry = new EligibilityRegistry(administrator);

        hrvSenior = new VaultShareToken(
            "CARE-HRV-01 Senior Interest",
            "HRV-S",
            address(registry),
            registry.CLASS_S(),
            administrator
        );

        hrvMezzanine = new VaultShareToken(
            "CARE-HRV-01 Mezzanine Interest",
            "HRV-M",
            address(registry),
            registry.CLASS_M(),
            administrator
        );

        hrvEquity = new VaultShareToken(
            "CARE-HRV-01 Equity Interest",
            "HRV-E",
            address(registry),
            registry.CLASS_E(),
            administrator
        );
    }
}
