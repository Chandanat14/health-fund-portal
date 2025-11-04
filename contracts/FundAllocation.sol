// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract FundAllocation {
    uint256 public constant MAX_CLAIM_PER_USER = 500000;
    uint256 public claimCount;
    address public treasurer;

    enum Status { Pending, Approved, Rejected }
    struct Claim {
        uint256 id;
        address hospital;
        uint256 amount;
        Status status;
        address approver;
    }

    mapping(uint256 => Claim) public claims;
    mapping(address => bool) public isRegisteredHospital;
    mapping(address => uint256) public totalClaimed;

    event ClaimSubmitted(uint256 indexed claimId, address indexed hospital, uint256 amount);

    constructor() {
        treasurer = msg.sender;
    }

    function registerHospital(address hospital) public {
        require(msg.sender == treasurer, "Only treasurer can call this function");
        isRegisteredHospital[hospital] = true;
    }

    function submitClaim(address hospital, uint256 amount) public {
        require(isRegisteredHospital[hospital], "Hospital not registered");
        require(amount > 0, "Amount must be greater than 0");
        require(totalClaimed[hospital] + amount <= MAX_CLAIM_PER_USER, "Exceeds claim limit");

        claimCount++;
        claims[claimCount] = Claim(claimCount, hospital, amount, Status.Pending, address(0));
        totalClaimed[hospital] += amount;

        emit ClaimSubmitted(claimCount, hospital, amount);
    }

    function approveClaim(uint256 claim_id) public {
        require(msg.sender == treasurer, "Only treasurer can call this function");
        require(claims[claim_id].id == claim_id, "Claim does not exist");
        require(claims[claim_id].status == Status.Pending, "Claim already processed");

        claims[claim_id].status = Status.Approved;
        claims[claim_id].approver = msg.sender;
    }

    function rejectClaim(uint256 claim_id) public {
        require(msg.sender == treasurer, "Only treasurer can call this function");
        require(claims[claim_id].id == claim_id, "Claim does not exist");
        require(claims[claim_id].status == Status.Pending, "Claim already processed");

        claims[claim_id].status = Status.Rejected;
        claims[claim_id].approver = msg.sender;
        totalClaimed[claims[claim_id].hospital] -= claims[claim_id].amount;
    }
}