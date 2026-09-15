// SPDX-License-Identifier: BUSL-1.1
pragma solidity ^0.8.24;

/// @title CareFi Eligibility Registry
/// @notice Compliance/eligibility state for permissioned CareFi vault interests.
/// @dev Prototype only. Not audited. The legal investor register remains off-chain.
contract EligibilityRegistry {
    uint8 public constant CLASS_S = 1 << 0;
    uint8 public constant CLASS_M = 1 << 1;
    uint8 public constant CLASS_E = 1 << 2;

    struct Eligibility {
        bool active;
        uint8 classMask;
        uint64 lockupUntil;
        bytes32 jurisdictionHash;
        address recoveryWallet;
        uint64 updatedAt;
    }

    address public owner;
    mapping(address => bool) public complianceAdmins;
    mapping(address => Eligibility) private _eligibility;
    mapping(address => address) public replacementWallet;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event ComplianceAdminSet(address indexed admin, bool allowed);
    event EligibilitySet(
        address indexed wallet,
        bool active,
        uint8 classMask,
        uint64 lockupUntil,
        bytes32 jurisdictionHash,
        address recoveryWallet
    );
    event WalletReplaced(address indexed oldWallet, address indexed newWallet);

    error Unauthorized();
    error ZeroAddress();
    error InvalidClassMask();
    error ReplacementNotEligible();

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlyCompliance() {
        if (msg.sender != owner && !complianceAdmins[msg.sender]) revert Unauthorized();
        _;
    }

    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert ZeroAddress();
        owner = initialOwner;
        emit OwnershipTransferred(address(0), initialOwner);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setComplianceAdmin(address admin, bool allowed) external onlyOwner {
        if (admin == address(0)) revert ZeroAddress();
        complianceAdmins[admin] = allowed;
        emit ComplianceAdminSet(admin, allowed);
    }

    function setEligibility(
        address wallet,
        bool active,
        uint8 classMask,
        uint64 lockupUntil,
        bytes32 jurisdictionHash,
        address recoveryWallet
    ) external onlyCompliance {
        if (wallet == address(0)) revert ZeroAddress();
        if (classMask > (CLASS_S | CLASS_M | CLASS_E)) revert InvalidClassMask();

        _eligibility[wallet] = Eligibility({
            active: active,
            classMask: classMask,
            lockupUntil: lockupUntil,
            jurisdictionHash: jurisdictionHash,
            recoveryWallet: recoveryWallet,
            updatedAt: uint64(block.timestamp)
        });

        emit EligibilitySet(
            wallet,
            active,
            classMask,
            lockupUntil,
            jurisdictionHash,
            recoveryWallet
        );
    }

    function eligibilityOf(address wallet) external view returns (Eligibility memory) {
        return _eligibility[wallet];
    }

    function isEligible(address wallet, uint8 classBit) public view returns (bool) {
        Eligibility memory e = _eligibility[wallet];
        return e.active && (e.classMask & classBit) != 0;
    }

    function isLocked(address wallet) public view returns (bool) {
        return block.timestamp < _eligibility[wallet].lockupUntil;
    }

    /// @notice Transfer policy used by each HRV token.
    /// @dev Both sides must remain eligible; sender must be outside its lock-up.
    function canTransfer(address from, address to, uint8 classBit) external view returns (bool) {
        return isEligible(from, classBit) && isEligible(to, classBit) && !isLocked(from);
    }

    /// @notice Move compliance identity to a replacement wallet after off-chain approval.
    /// @dev Token balances are migrated separately by each share token's recoverWallet().
    function replaceWallet(address oldWallet, address newWallet) external onlyCompliance {
        if (oldWallet == address(0) || newWallet == address(0)) revert ZeroAddress();
        Eligibility memory oldEligibility = _eligibility[oldWallet];
        if (!oldEligibility.active) revert ReplacementNotEligible();

        Eligibility memory newEligibility = _eligibility[newWallet];
        if (!newEligibility.active) {
            _eligibility[newWallet] = Eligibility({
                active: true,
                classMask: oldEligibility.classMask,
                lockupUntil: oldEligibility.lockupUntil,
                jurisdictionHash: oldEligibility.jurisdictionHash,
                recoveryWallet: oldWallet,
                updatedAt: uint64(block.timestamp)
            });
        } else if ((newEligibility.classMask & oldEligibility.classMask) != oldEligibility.classMask) {
            revert ReplacementNotEligible();
        }

        _eligibility[oldWallet].active = false;
        _eligibility[oldWallet].updatedAt = uint64(block.timestamp);
        replacementWallet[oldWallet] = newWallet;
        emit WalletReplaced(oldWallet, newWallet);
    }
}
