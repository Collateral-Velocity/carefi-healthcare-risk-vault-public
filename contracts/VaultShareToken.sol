// SPDX-License-Identifier: BUSL-1.1
pragma solidity ^0.8.24;

import "./EligibilityRegistry.sol";

/// @title CareFi Permissioned Vault Share
/// @notice ERC-20-compatible accounting token with compliance-gated transfers.
/// @dev Prototype only. Not audited. Does not itself create a legal security or fund interest.
contract VaultShareToken {
    string public name;
    string public symbol;
    uint8 public constant decimals = 18;

    EligibilityRegistry public immutable eligibilityRegistry;
    uint8 public immutable classBit;

    address public owner;
    mapping(address => bool) public operators;
    bool public transfersPaused;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event OperatorSet(address indexed operator, bool allowed);
    event TransfersPaused(bool paused);
    event WalletBalanceRecovered(address indexed oldWallet, address indexed newWallet, uint256 amount);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error Unauthorized();
    error ZeroAddress();
    error InvalidAmount();
    error InsufficientBalance();
    error InsufficientAllowance();
    error TransferRestricted();
    error TransfersArePaused();
    error InvalidRecovery();

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlyOperator() {
        if (msg.sender != owner && !operators[msg.sender]) revert Unauthorized();
        _;
    }

    constructor(
        string memory tokenName,
        string memory tokenSymbol,
        address registry,
        uint8 tokenClassBit,
        address initialOwner
    ) {
        if (registry == address(0) || initialOwner == address(0)) revert ZeroAddress();
        name = tokenName;
        symbol = tokenSymbol;
        eligibilityRegistry = EligibilityRegistry(registry);
        classBit = tokenClassBit;
        owner = initialOwner;
        emit OwnershipTransferred(address(0), initialOwner);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setOperator(address operator, bool allowed) external onlyOwner {
        if (operator == address(0)) revert ZeroAddress();
        operators[operator] = allowed;
        emit OperatorSet(operator, allowed);
    }

    function pauseTransfers(bool paused) external onlyOwner {
        transfersPaused = paused;
        emit TransfersPaused(paused);
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _restrictedTransfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed < amount) revert InsufficientAllowance();
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - amount;
            emit Approval(from, msg.sender, allowance[from][msg.sender]);
        }
        _restrictedTransfer(from, to, amount);
        return true;
    }

    /// @notice Mint only after the off-chain subscription has been accepted/funded.
    function mint(address to, uint256 amount) external onlyOperator {
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert InvalidAmount();
        if (!eligibilityRegistry.isEligible(to, classBit)) revert TransferRestricted();
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    /// @notice Burn after an approved redemption or legal cancellation.
    /// @dev Operator-controlled so lock-up/redemption policy remains outside unilateral token-holder control.
    function burn(address from, uint256 amount) external onlyOperator {
        if (amount == 0) revert InvalidAmount();
        uint256 bal = balanceOf[from];
        if (bal < amount) revert InsufficientBalance();
        balanceOf[from] = bal - amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }

    /// @notice Migrate the entire balance after compliance approves wallet replacement.
    function recoverWallet(address oldWallet) external onlyOperator returns (uint256 amount) {
        address newWallet = eligibilityRegistry.replacementWallet(oldWallet);
        if (
            newWallet == address(0) ||
            eligibilityRegistry.isEligible(oldWallet, classBit) ||
            !eligibilityRegistry.isEligible(newWallet, classBit)
        ) revert InvalidRecovery();

        amount = balanceOf[oldWallet];
        if (amount == 0) revert InvalidAmount();
        balanceOf[oldWallet] = 0;
        balanceOf[newWallet] += amount;
        emit Transfer(oldWallet, newWallet, amount);
        emit WalletBalanceRecovered(oldWallet, newWallet, amount);
    }

    function _restrictedTransfer(address from, address to, uint256 amount) internal {
        if (transfersPaused) revert TransfersArePaused();
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert InvalidAmount();
        if (!eligibilityRegistry.canTransfer(from, to, classBit)) revert TransferRestricted();
        uint256 bal = balanceOf[from];
        if (bal < amount) revert InsufficientBalance();
        balanceOf[from] = bal - amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
