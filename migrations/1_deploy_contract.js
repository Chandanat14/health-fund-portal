const FundAllocation = artifacts.require("FundAllocation");

module.exports = function (deployer) {
  deployer.deploy(FundAllocation, { gas: 5000000 });
};