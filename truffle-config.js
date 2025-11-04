module.exports = {
  networks: {
    development: {
      host: "127.0.0.1",
      port: 7545,
      network_id: "5777", // Match Ganache network ID
      gas: 6721975, // Match block gas limit
      gasPrice: 20000000000 // 20 Gwei
    }
  },
  compilers: {
    solc: {
      version: "0.8.20", // Explicitly set to a stable 0.8.x version
      settings: {
        optimizer: {
          enabled: true,
          runs: 200
        },
        evmVersion: "london" // Compatible EVM version
      }
    }
  },
  contracts_directory: './contracts/',
  contracts_build_directory: './build/contracts'
};